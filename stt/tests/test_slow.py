"""End-to-end test with the real faster-whisper and a real download from Hugging Face.

Run explicitly: ``STT_SLOW_DATA_DIR=/some/dir pytest -m slow``. It downloads the
tiny model (~78 MB) and a sample from the faster-whisper repo into that dir.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pytest
from conftest import write_video
from fastapi.testclient import TestClient

from stt.audio import decode_audio
from stt.config import Settings
from stt.main import create_app
from stt.registry import ModelFile, ModelSpec

pytestmark = pytest.mark.slow

TINY = ModelSpec(
    name="tiny",
    repo="Systran/faster-whisper-tiny",
    revision="d90ca5fe260221311c53c58e660288d3deb8d356",
    files=(
        ModelFile("config.json", 2249, git_sha1="3baa18e2b321a2f489614607852a729fcd516480"),
        ModelFile("vocabulary.txt", 459861, git_sha1="c9074644d9d1205686f16d411564729461324b75"),
        ModelFile("tokenizer.json", 2203239, git_sha1="7818adb6de9fa3064d3ff81226fdd675be1f6344"),
        ModelFile(
            "model.bin",
            75538270,
            sha256="dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
        ),
    ),
)

JFK_URL = (
    "https://raw.githubusercontent.com/SYSTRAN/faster-whisper/"
    "66efd02bd0c43a8488c9f3fd292d67f045623669/tests/data/jfk.flac"
)
JFK_SHA256 = "63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715"


@pytest.fixture(scope="module")
def data_dir() -> Path:
    raw = os.environ.get("STT_SLOW_DATA_DIR")
    if not raw:
        pytest.skip("set STT_SLOW_DATA_DIR to run the slow end-to-end test")
    root = Path(raw)
    (root / "files").mkdir(parents=True, exist_ok=True)
    jfk = root / "files" / "jfk.flac"
    if not jfk.exists():
        with urllib.request.urlopen(JFK_URL, timeout=60) as response:
            jfk.write_bytes(response.read())
    assert hashlib.sha256(jfk.read_bytes()).hexdigest() == JFK_SHA256
    write_video(root / "files" / "jfk.mp4", decode_audio(jfk), 11.0)
    with wave.open(str(root / "files" / "silence.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.zeros(16000 * 5, dtype=np.int16).tobytes())
    return root


@pytest.fixture(scope="module")
def client(data_dir):
    settings = Settings(data_dir=data_dir, idle_unload_s=0, registry={"tiny": TINY})
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_transcribe_downloads_and_recognises(client, data_dir):
    assert client.get("/models").json()[0]["downloaded"] is False
    r = client.post("/transcribe", json={"input": "files/jfk.mp4", "model": "tiny"})
    assert r.status_code == 200, r.text
    body = r.json()
    print(body["text"])
    assert "fellow Americans" in body["text"]
    assert body["language"] == "en"
    assert 10.5 < body["duration"] < 11.5
    assert body["segments"] and body["words"]
    last_end = 0.0
    for word in body["words"]:
        assert word["word"] == word["word"].strip() != ""
        assert 0.0 <= word["start"] <= word["end"] <= body["duration"] + 0.5
        assert word["start"] >= last_end - 0.5
        assert 0.0 <= word["probability"] <= 1.0
        last_end = word["end"]
    assert client.get("/models").json()[0]["downloaded"] is True


def test_forced_language_and_no_words(client):
    r = client.post(
        "/transcribe",
        json={
            "input": "files/jfk.flac",
            "model": "tiny",
            "language": "en",
            "word_timestamps": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["words"] == []
    assert "country" in r.json()["text"]


def test_silence(client):
    r = client.post("/transcribe", json={"input": "files/silence.wav", "model": "tiny"})
    assert r.status_code == 200, r.text
    body = r.json()
    print(body)
    assert body["segments"] == []
    assert body["text"] == ""


def test_delete(client, data_dir):
    r = client.delete("/models/tiny")
    assert r.status_code == 200
    assert r.json()["downloaded"] is False
    assert not (data_dir / "models" / "tiny").exists()
