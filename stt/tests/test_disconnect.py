"""A client that goes away stops its transcription (real uvicorn, fake Whisper)."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import uvicorn
from conftest import CONTENTS, FAKE_A, FakeFactory, install_model, write_wav

from stt.config import Settings
from stt.main import create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def test_disconnect_cancels_transcription(tmp_path):
    data_dir = tmp_path / "data"
    install_model(data_dir / "models", FAKE_A, CONTENTS["fake-a"])
    write_wav(data_dir / "files" / "a.wav", 3.0)
    factory = FakeFactory()
    factory.gate = threading.Event()
    settings = Settings(
        data_dir=data_dir,
        idle_unload_s=0,
        cpu_threads=1,
        hf_endpoint="http://127.0.0.1:9",
        registry={FAKE_A.name: FAKE_A},
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, model_factory=factory),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(0.02)

        body = json.dumps({"input": "files/a.wav", "model": "fake-a"}).encode()
        client = socket.create_connection(("127.0.0.1", port))
        client.sendall(
            b"POST /transcribe HTTP/1.1\r\nHost: stt\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
        )
        while get_json(f"{base}/progress")["phase"] != "transcribing":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        client.close()
        time.sleep(1.5)  # the endpoint notices the disconnect within DISCONNECT_POLL_S
        factory.gate.set()

        deadline = time.monotonic() + 10
        while get_json(f"{base}/health")["busy"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        # Stopped after the first segment instead of running to the end.
        assert factory.models[0].yielded == 1
    finally:
        factory.gate.set()
        server.should_exit = True
        thread.join(10)
