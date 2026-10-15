from __future__ import annotations

import threading
import time

import pytest
from conftest import FakeFactory, write_video, write_wav

from stt.config import Settings
from stt.main import create_app


def transcribe(env, **body):
    payload = {"input": "files/a.wav", "model": "fake-a", "language": "auto"}
    payload.update(body)
    return env.client.post("/transcribe", json=payload)


@pytest.fixture
def wav(env):
    return write_wav(env.data_dir / "files" / "a.wav", 3.0)


def test_health(env):
    r = env.client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "1.2.3-test", "busy": False}


def test_models_list(env):
    r = env.client.get("/models")
    assert r.status_code == 200
    assert [m["name"] for m in r.json()] == ["fake-a", "fake-b"]
    assert r.json()[0] == {
        "name": "fake-a",
        "size_mb": 0,
        "downloaded": False,
        "downloading": False,
        "progress": None,
        "error": None,
    }
    env.install("fake-a")
    assert env.client.get("/models").json()[0]["downloaded"] is True


def test_default_registry_lists_two_models(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(Settings(data_dir=tmp_path), model_factory=FakeFactory())
    with TestClient(app) as client:
        models = client.get("/models").json()
    assert [(m["name"], m["size_mb"]) for m in models] == [("large-v3-turbo", 1622), ("small", 486)]


def test_transcribe_verbose_json(env, wav):
    env.install("fake-a")
    r = transcribe(env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "task": "transcribe",
        "language": "en",
        "duration": 3.0,
        "text": "Hello world. Second line",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 1.234,
                "text": "Hello world.",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.9877},
                    {"word": "world.", "start": 0.5, "end": 1.234, "probability": 0.9},
                ],
            },
            {
                "id": 1,
                "start": 1.5,
                "end": 2.75,
                "text": "Second line",
                "words": [
                    {"word": "Second", "start": 1.5, "end": 2.0, "probability": 0.8},
                    {"word": "line", "start": 2.0, "end": 2.75, "probability": 0.7},
                ],
            },
        ],
        "words": [
            {"word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.9877},
            {"word": "world.", "start": 0.5, "end": 1.234, "probability": 0.9},
            {"word": "Second", "start": 1.5, "end": 2.0, "probability": 0.8},
            {"word": "line", "start": 2.0, "end": 2.75, "probability": 0.7},
        ],
        "model": "fake-a",
    }
    (model,) = env.factory.models
    call = model.calls[0]
    assert call["samples"] == 48000
    assert call["language"] is None
    assert call["word_timestamps"] is True
    assert call["vad_filter"] is True
    assert call["beam_size"] == 5
    assert env.factory.loads == [(env.models_dir / "fake-a", 2)]


def test_transcribe_language_and_no_words(env, wav):
    env.install("fake-a")
    r = transcribe(env, language="uk", word_timestamps=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "uk"
    assert body["words"] == []
    assert all(seg["words"] == [] for seg in body["segments"])
    call = env.factory.models[0].calls[0]
    assert call["language"] == "uk"
    assert call["word_timestamps"] is False


def test_transcribe_video_file(env):
    env.install("fake-a")
    from conftest import tone

    write_video(env.data_dir / "files" / "clip.mp4", tone(2.0), 2.0)
    r = transcribe(env, input="files/clip.mp4")
    assert r.status_code == 200, r.text
    samples = env.factory.models[0].calls[0]["samples"]
    assert abs(samples - 32000) < 3000  # aac priming / padding


def test_video_without_audio(env):
    env.install("fake-a")
    write_video(env.data_dir / "files" / "mute.mp4", None, 1.0)
    r = transcribe(env, input="files/mute.mp4")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_audio"


def test_not_media(env):
    env.install("fake-a")
    (env.data_dir / "files").mkdir()
    (env.data_dir / "files" / "x.wav").write_bytes(b"this is not audio" * 100)
    r = transcribe(env, input="files/x.wav")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "transcribe_failed"


def test_model_stays_loaded_and_switches(env, wav):
    env.install("fake-a")
    env.install("fake-b")
    assert transcribe(env).status_code == 200
    assert transcribe(env).status_code == 200
    assert len(env.factory.loads) == 1
    assert transcribe(env, model="fake-b").status_code == 200
    assert [p.name for p, _ in env.factory.loads] == ["fake-a", "fake-b"]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"input": "/etc/passwd"}, 400, "bad_request"),
        ({"input": "../x.wav"}, 400, "bad_request"),
        ({"input": "files/missing.wav"}, 404, "not_found"),
        ({"input": "secrets/key.json"}, 400, "bad_request"),
        ({"language": "de"}, 400, "bad_request"),
        ({"model": "medium"}, 404, "model_not_found"),
        ({"word_timestamps": "yes"}, 400, "bad_request"),
        ({"input": 5}, 400, "bad_request"),
        ({"extra": 1}, 400, "bad_request"),
    ],
)
def test_transcribe_validation(env, wav, body, status, code):
    (env.data_dir / "secrets").mkdir()
    (env.data_dir / "secrets" / "key.json").write_text("{}")
    r = transcribe(env, **body)
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]


def test_default_model_is_large_v3_turbo(env, wav):
    r = env.client.post("/transcribe", json={"input": "files/a.wav"})
    assert r.status_code == 404
    assert "'large-v3-turbo'" in r.json()["error"]["message"]


def test_bad_json_and_unknown_route(env):
    r = env.client.post(
        "/transcribe", content=b"{nope", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"
    r = env.client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_busy_and_progress(env, wav):
    env.install("fake-a")
    env.factory.gate = threading.Event()
    result = {}

    def first():
        result["r"] = transcribe(env)

    worker = threading.Thread(target=first)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while env.client.get("/progress").json()["phase"] != "transcribing":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        progress = env.client.get("/progress").json()
        assert progress["busy"] is True
        assert progress["model"] == "fake-a"
        assert progress["progress"] == 0.0
        assert progress["duration"] == 3.0
        assert progress["elapsed_s"] >= 0
        assert env.client.get("/health").json()["busy"] is True

        r = transcribe(env)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "busy"

        r = env.client.delete("/models/fake-a")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "busy"
    finally:
        env.factory.gate.set()
        worker.join(10)
    assert result["r"].status_code == 200
    assert env.client.get("/progress").json() == {
        "busy": False,
        "phase": None,
        "progress": None,
        "model": None,
        "duration": None,
        "elapsed_s": None,
    }
    assert env.client.get("/health").json()["busy"] is False


def test_transcribe_downloads_missing_model(env, wav):
    r = transcribe(env)
    assert r.status_code == 200, r.text
    status = env.client.get("/models").json()[0]
    assert status["downloaded"] is True
    assert status["downloading"] is False
    assert (env.models_dir / "fake-a" / "model.bin").is_file()


def test_transcribe_download_failure(env, wav):
    env.hub.fail["model.bin"] = 404
    r = transcribe(env)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "download_failed"
    status = env.client.get("/models").json()[0]
    assert status["downloaded"] is False
    assert "HTTP 404" in status["error"]


def test_download_endpoint(env):
    r = env.client.post("/models/download", json={"name": "fake-a"})
    assert r.status_code == 202
    assert r.json()["name"] == "fake-a"
    status = env.wait_downloaded("fake-a")
    assert status == {
        "name": "fake-a",
        "size_mb": 0,
        "downloaded": True,
        "downloading": False,
        "progress": None,
        "error": None,
    }
    r = env.client.post("/models/download", json={"name": "fake-a"})
    assert r.status_code == 200
    assert r.json()["downloaded"] is True


def test_download_progress_is_visible(env):
    env.hub.chunk = 16 * 1024
    env.hub.delay_s = 0.02
    r = env.client.post("/models/download", json={"name": "fake-a"})
    assert r.status_code == 202
    seen = set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = env.client.get("/models").json()[0]
        if not status["downloading"]:
            break
        assert 0.0 <= status["progress"] <= 1.0
        seen.add(status["progress"])
        time.sleep(0.01)
    assert status["downloaded"] is True
    assert len(seen) > 2


def test_download_unknown_or_bad(env):
    r = env.client.post("/models/download", json={"name": "huge"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"
    r = env.client.post("/models/download", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_delete(env, wav):
    env.install("fake-a")
    assert transcribe(env).status_code == 200
    r = env.client.delete("/models/fake-a")
    assert r.status_code == 200
    assert r.json()["downloaded"] is False
    assert not (env.models_dir / "fake-a").exists()
    # idempotent
    assert env.client.delete("/models/fake-a").status_code == 200
    r = env.client.delete("/models/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


def test_delete_cancels_download(env):
    env.hub.chunk = 4 * 1024
    env.hub.delay_s = 0.05
    assert env.client.post("/models/download", json={"name": "fake-a"}).status_code == 202
    deadline = time.monotonic() + 10
    while not (env.models_dir / ".partial-fake-a").exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    r = env.client.delete("/models/fake-a")
    assert r.status_code == 200
    assert r.json()["downloading"] is False
    assert r.json()["downloaded"] is False
    assert not (env.models_dir / ".partial-fake-a").exists()
    assert not (env.models_dir / "fake-a").exists()
