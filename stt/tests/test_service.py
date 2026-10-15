from __future__ import annotations

import threading

import numpy as np
import pytest
from conftest import CONTENTS, FAKE_A, FakeFactory, install_model

from stt.engine import WhisperEngine
from stt.errors import Cancelled, ServiceError
from stt.models import ModelStore
from stt.service import Job, SttService


def make_service(tmp_path, factory, decoder):
    store = ModelStore(tmp_path / "models", {"fake-a": FAKE_A}, "http://127.0.0.1:9")
    install_model(store.models_dir, FAKE_A, CONTENTS["fake-a"])
    return SttService(store, WhisperEngine(1, 0, factory), decoder)


def silence(path, stop=None, on_progress=None):
    return np.zeros(16000 * 3, dtype=np.float32)


JOB = Job(path=None, model="fake-a", language="auto", word_timestamps=True)  # type: ignore[arg-type]


def test_cancel_during_transcription_releases_slot(tmp_path):
    factory = FakeFactory()
    factory.gate = threading.Event()
    service = make_service(tmp_path, factory, silence)
    stop = threading.Event()
    assert service.try_begin("fake-a")
    assert service.try_begin("fake-a") is False
    outcome = {}

    def worker():
        try:
            outcome["result"] = service.run(JOB, stop)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    stop.set()
    factory.gate.set()
    thread.join(10)
    assert isinstance(outcome.get("error"), Cancelled)
    assert service.busy is False
    assert service.progress()["busy"] is False
    # The model was released and can be deleted now.
    assert service.delete_model("fake-a")["downloaded"] is False


def test_cancel_during_decoding(tmp_path):
    stop = threading.Event()

    def decoder(path, stop_event, on_progress):
        stop_event.set()  # the client disconnects while decoding
        raise Cancelled()

    service = make_service(tmp_path, FakeFactory(), decoder)
    assert service.try_begin("fake-a")
    with pytest.raises(Cancelled):
        service.run(JOB, stop)
    assert service.busy is False


def test_unexpected_error_becomes_transcribe_failed(tmp_path):
    def broken(model_dir, threads):
        raise RuntimeError("cannot load model.bin")

    service = make_service(tmp_path, broken, silence)
    assert service.try_begin("fake-a")
    with pytest.raises(ServiceError) as exc:
        service.run(JOB, threading.Event())
    assert exc.value.code == "transcribe_failed"
    assert "cannot load model.bin" in exc.value.message
    assert service.busy is False


def test_empty_result(tmp_path):
    service = make_service(tmp_path, FakeFactory(script=[]), silence)
    assert service.try_begin("fake-a")
    result = service.run(JOB, threading.Event())
    assert result["text"] == ""
    assert result["segments"] == []
    assert result["words"] == []
    assert result["duration"] == 3.0


def test_progress_phases(tmp_path):
    factory = FakeFactory()
    factory.gate = threading.Event()
    seen = []

    def decoder(path, stop, on_progress):
        on_progress(0.5)
        seen.append(service.progress())
        return np.zeros(16000 * 4, dtype=np.float32)

    service = make_service(tmp_path, factory, decoder)
    assert service.try_begin("fake-a")
    assert service.progress()["phase"] == "starting"
    thread = threading.Thread(target=service.run, args=(JOB, threading.Event()))
    thread.start()
    factory.gate.set()
    thread.join(10)
    assert seen[0]["phase"] == "decoding"
    assert seen[0]["progress"] == 0.5
    assert seen[0]["model"] == "fake-a"
