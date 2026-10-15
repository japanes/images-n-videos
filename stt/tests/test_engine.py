from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import FakeFactory

from stt.engine import WhisperEngine

A, B = Path("/m/a"), Path("/m/b")


def test_reuse_and_switch():
    factory = FakeFactory()
    engine = WhisperEngine(3, 0, factory)
    first = engine.acquire("a", A)
    engine.release()
    assert engine.acquire("a", A) is first
    engine.release()
    assert factory.loads == [(A, 3)]
    second = engine.acquire("b", B)
    engine.release()
    assert second is not first
    assert engine.loaded_name == "b"
    assert factory.loads == [(A, 3), (B, 3)]


def test_unload_only_when_idle_and_matching():
    engine = WhisperEngine(1, 0, FakeFactory())
    engine.acquire("a", A)
    assert engine.unload() is False  # in use
    engine.release()
    assert engine.unload("b") is False
    assert engine.unload("a") is True
    assert engine.loaded_name is None
    assert engine.unload() is False


def test_cannot_switch_while_in_use():
    engine = WhisperEngine(1, 0, FakeFactory())
    engine.acquire("a", A)
    with pytest.raises(RuntimeError):
        engine.acquire("b", B)


def test_failed_load_leaves_engine_usable():
    calls = []

    def factory(model_dir, threads):
        calls.append(model_dir)
        if len(calls) == 1:
            raise OSError("broken model")
        return object()

    engine = WhisperEngine(1, 0, factory)
    with pytest.raises(OSError):
        engine.acquire("a", A)
    assert engine.loaded_name is None
    engine.acquire("a", A)
    engine.release()
    assert engine.loaded_name == "a"


def test_idle_unload():
    engine = WhisperEngine(1, 1, FakeFactory(), check_interval_s=0.05)
    try:
        engine.acquire("a", A)
        time.sleep(1.3)
        assert engine.loaded_name == "a"  # still in use: never unloaded
        engine.release()
        deadline = time.monotonic() + 5
        while engine.loaded_name is not None:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        engine.close()
