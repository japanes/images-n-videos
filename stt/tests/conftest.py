"""Shared fixtures: a fake Hugging Face server, fake Whisper models, media files."""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from stt.config import Settings
from stt.main import create_app
from stt.models import MANIFEST
from stt.registry import ModelFile, ModelSpec

# ---------------------------------------------------------------- model specs


def make_spec(
    name: str, contents: dict[str, bytes], repo: str = "test/fake", revision: str = "rev1"
) -> ModelSpec:
    files = []
    for path, data in contents.items():
        if path == "model.bin":
            files.append(ModelFile(path, len(data), sha256=hashlib.sha256(data).hexdigest()))
        else:
            blob = b"blob %d\0" % len(data) + data
            files.append(ModelFile(path, len(data), git_sha1=hashlib.sha1(blob).hexdigest()))
    return ModelSpec(name=name, repo=repo, revision=revision, files=tuple(files))


def model_contents(seed: int, size: int = 300_000) -> dict[str, bytes]:
    rng = np.random.default_rng(seed)
    return {
        "config.json": json.dumps({"seed": seed}).encode(),
        "tokenizer.json": b'{"tok": %d}' % seed,
        "model.bin": rng.integers(0, 256, size, dtype=np.uint8).tobytes(),
    }


def install_model(models_dir: Path, spec: ModelSpec, contents: dict[str, bytes]) -> Path:
    """Put a complete model on disk the way a finished download leaves it."""
    final = models_dir / spec.name
    final.mkdir(parents=True, exist_ok=True)
    for path, data in contents.items():
        (final / path).write_bytes(data)
    (final / MANIFEST).write_text(json.dumps({"name": spec.name, "revision": spec.revision}))
    return final


# ---------------------------------------------------------------- fake hub


class FakeHub:
    """Serves /<repo>/resolve/<rev>/<path> with a redirect to a CDN path, like the Hub."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], bytes] = {}
        self.ignore_range = False
        self.fail: dict[str, int] = {}
        self.corrupt: set[str] = set()
        self.cut_once: set[str] = set()
        self.chunk = 64 * 1024
        self.delay_s = 0.0
        self.requests: list[tuple[str, str | None]] = []
        self.resolves: list[str] = []
        self._lock = threading.Lock()
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                hub._handle(self)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def add(self, spec: ModelSpec, contents: dict[str, bytes]) -> None:
        for path, data in contents.items():
            self.files[(spec.repo, spec.revision, path)] = data

    def range_requests(self, path: str) -> list[str | None]:
        return [r for p, r in self.requests if p == path]

    def _handle(self, req: http.server.BaseHTTPRequestHandler) -> None:
        if "/resolve/" in req.path:
            repo, rest = req.path.lstrip("/").split("/resolve/", 1)
            rev, path = rest.split("/", 1)
            with self._lock:
                self.resolves.append(path)
            if path in self.fail:
                req.send_error(self.fail[path])
                return
            req.send_response(302)
            req.send_header("Location", f"/cdn/{repo}/{rev}/{path}")
            req.send_header("Content-Length", "0")
            req.end_headers()
            return
        if not req.path.startswith("/cdn/"):
            req.send_error(404)
            return
        org, name, rev, path = req.path[len("/cdn/") :].split("/", 3)
        data = self.files.get((f"{org}/{name}", rev, path))
        if data is None:
            req.send_error(404)
            return
        if path in self.corrupt:
            data = bytes(b ^ 0xFF for b in data[:16]) + data[16:]
        rng = req.headers.get("Range")
        with self._lock:
            self.requests.append((path, rng))
        start = 0
        if rng and not self.ignore_range:
            start = int(rng.removeprefix("bytes=").split("-")[0])
            req.send_response(206)
            req.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            req.send_response(200)
        body = data[start:]
        req.send_header("Content-Length", str(len(body)))
        req.end_headers()
        if path in self.cut_once:
            self.cut_once.discard(path)
            body = body[: len(body) // 2]
            req.wfile.write(body)
            req.wfile.flush()
            req.close_connection = True
            return
        try:
            for i in range(0, len(body), self.chunk):
                req.wfile.write(body[i : i + self.chunk])
                if self.delay_s:
                    time.sleep(self.delay_s)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def hub() -> Iterator[FakeHub]:
    server = FakeHub()
    yield server
    server.close()


# ---------------------------------------------------------------- fake whisper


class FakeWhisper:
    """Mimics faster_whisper.WhisperModel.transcribe (generator of segments + info)."""

    def __init__(self, model_dir: Path, script: list[dict], gate: threading.Event | None) -> None:
        self.model_dir = model_dir
        self.script = script
        self.gate = gate
        self.calls: list[dict] = []
        self.yielded = 0

    def transcribe(self, audio, **kwargs):
        self.calls.append({"samples": len(audio), **kwargs})
        duration = len(audio) / 16000
        word_ts = kwargs.get("word_timestamps", False)

        def segments():
            for i, item in enumerate(self.script):
                if self.gate is not None:
                    assert self.gate.wait(10), "test gate was never opened"
                words = None
                if word_ts:
                    words = [SimpleNamespace(**w) for w in item["words"]]
                self.yielded += 1
                yield SimpleNamespace(
                    id=i + 1,
                    start=item["start"],
                    end=item["end"],
                    text=item["text"],
                    words=words,
                )

        info = SimpleNamespace(language=kwargs.get("language") or "en", duration=duration)
        return segments(), info


DEFAULT_SCRIPT = [
    {
        "start": 0.0,
        "end": 1.2345,
        "text": " Hello world.",
        "words": [
            {"word": " Hello", "start": 0.0, "end": 0.5, "probability": 0.98765},
            {"word": " world.", "start": 0.5, "end": 1.2345, "probability": 0.9},
        ],
    },
    {
        "start": 1.5,
        "end": 2.75,
        "text": " Second line",
        "words": [
            {"word": " Second", "start": 1.5, "end": 2.0, "probability": 0.8},
            {"word": " ", "start": 2.0, "end": 2.0, "probability": 0.1},
            {"word": " line", "start": 2.0, "end": 2.75, "probability": 0.7},
        ],
    },
]


class FakeFactory:
    def __init__(self, script: list[dict] | None = None) -> None:
        self.script = script if script is not None else DEFAULT_SCRIPT
        self.gate: threading.Event | None = None
        self.loads: list[tuple[Path, int]] = []
        self.models: list[FakeWhisper] = []

    def __call__(self, model_dir: Path, cpu_threads: int) -> FakeWhisper:
        self.loads.append((model_dir, cpu_threads))
        model = FakeWhisper(model_dir, self.script, self.gate)
        self.models.append(model)
        return model


# ---------------------------------------------------------------- media files


def write_wav(path: Path, seconds: float, rate: int = 16000, channels: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * rate)) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(tone[:, None], channels, axis=1).tobytes())
    return path


def write_video(path: Path, audio: np.ndarray | None, seconds: float, rate: int = 16000) -> Path:
    """Write an .mp4 with a tiny video track and (optionally) the given mono float32 audio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fps = 10
    with av.open(str(path), "w") as out:
        video = out.add_stream("mpeg4", rate=fps)
        video.width, video.height, video.pix_fmt = 64, 64, "yuv420p"
        sound = None
        if audio is not None:
            sound = out.add_stream("aac", rate=rate, layout="mono")
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        for i in range(int(seconds * fps)):
            frame = av.VideoFrame.from_ndarray(black, format="rgb24")
            frame.pts = i
            out.mux(video.encode(frame))
        out.mux(video.encode(None))
        if sound is not None:
            for i in range(0, len(audio), 1024):
                chunk = audio[i : i + 1024].astype(np.float32)[None, :]
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="mono")
                frame.sample_rate = rate
                frame.pts = i
                out.mux(sound.encode(frame))
            out.mux(sound.encode(None))
    return path


def tone(seconds: float, rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * 330 * t) * 0.3).astype(np.float32)


# ---------------------------------------------------------------- app


FAKE_A = make_spec("fake-a", model_contents(1), repo="test/fake-a")
FAKE_B = make_spec("fake-b", model_contents(2), repo="test/fake-b")
CONTENTS = {"fake-a": model_contents(1), "fake-b": model_contents(2)}


class AppEnv(SimpleNamespace):
    client: TestClient
    data_dir: Path
    models_dir: Path
    factory: FakeFactory
    hub: FakeHub

    def install(self, name: str) -> Path:
        spec = self.client.app.state.settings.registry[name]
        return install_model(self.models_dir, spec, CONTENTS[name])

    def wait_downloaded(self, name: str, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = next(m for m in self.client.get("/models").json() if m["name"] == name)
            if not status["downloading"]:
                return status
            time.sleep(0.02)
        raise AssertionError(f"{name} still downloading")


@pytest.fixture
def env(tmp_path: Path, hub: FakeHub) -> Iterator[AppEnv]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for spec in (FAKE_A, FAKE_B):
        hub.add(spec, CONTENTS[spec.name])
    settings = Settings(
        data_dir=data_dir,
        version="1.2.3-test",
        cpu_threads=2,
        idle_unload_s=0,
        hf_endpoint=hub.url,
        registry={FAKE_A.name: FAKE_A, FAKE_B.name: FAKE_B},
    )
    factory = FakeFactory()
    app = create_app(
        settings,
        model_factory=factory,
        store_options={"retry_delay_s": 0.01, "timeout_s": 5},
    )
    with TestClient(app) as client:
        yield AppEnv(
            client=client,
            data_dir=data_dir,
            models_dir=data_dir / "models",
            factory=factory,
            hub=hub,
        )
