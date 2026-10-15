from __future__ import annotations

import json
import threading
import time
from collections import namedtuple

import pytest
from conftest import install_model, make_spec, model_contents

from stt import models as models_mod
from stt.errors import Cancelled, ServiceError
from stt.models import MANIFEST, ModelStore

SPEC = make_spec("m", model_contents(7), repo="org/m")
CONTENTS = model_contents(7)


@pytest.fixture
def store(tmp_path, hub):
    hub.add(SPEC, CONTENTS)
    return ModelStore(tmp_path / "models", {"m": SPEC}, hub.url, timeout_s=5, retry_delay_s=0.01)


def wait(store, name="m"):
    return store.wait_ready(name, threading.Event())


def assert_complete(store):
    final = store.models_dir / "m"
    for path, data in CONTENTS.items():
        assert (final / path).read_bytes() == data
    manifest = json.loads((final / MANIFEST).read_text())
    assert manifest["revision"] == SPEC.revision
    assert not (store.models_dir / ".partial-m").exists()
    assert store.is_downloaded("m")


def test_download_and_status(store, hub):
    assert store.status("m") == {
        "name": "m",
        "size_mb": 0,
        "downloaded": False,
        "downloading": False,
        "progress": None,
        "error": None,
    }
    accepted, status = store.start_download("m")
    assert accepted is True
    assert status["downloading"] is True
    assert 0.0 <= status["progress"] <= 1.0
    assert wait(store) == store.models_dir / "m"
    assert_complete(store)
    assert store.status("m")["downloaded"] is True
    # Fetched through the redirect, no Range on a fresh download.
    assert hub.range_requests("model.bin") == [None]
    accepted, status = store.start_download("m")
    assert accepted is False
    assert status["downloaded"] is True


def test_unknown_model(store):
    with pytest.raises(ServiceError) as exc:
        store.status("nope")
    assert exc.value.code == "model_not_found"


def test_resume_with_range(store, hub):
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    (partial / ".vf-revision").write_text(SPEC.revision)
    (partial / "model.bin").write_bytes(CONTENTS["model.bin"][:100_000])
    wait(store)
    assert_complete(store)
    assert hub.range_requests("model.bin") == ["bytes=100000-"]


def test_server_ignores_range(store, hub):
    hub.ignore_range = True
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    (partial / ".vf-revision").write_text(SPEC.revision)
    (partial / "model.bin").write_bytes(CONTENTS["model.bin"][:100_000])
    wait(store)
    assert_complete(store)


def test_complete_file_in_partial_is_verified_not_refetched(store, hub):
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    (partial / ".vf-revision").write_text(SPEC.revision)
    (partial / "model.bin").write_bytes(CONTENTS["model.bin"])
    wait(store)
    assert_complete(store)
    assert hub.range_requests("model.bin") == []


def test_corrupt_complete_file_in_partial_is_refetched(store, hub):
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    (partial / ".vf-revision").write_text(SPEC.revision)
    bad = bytearray(CONTENTS["model.bin"])
    bad[0] ^= 0xFF
    (partial / "model.bin").write_bytes(bytes(bad))
    wait(store)
    assert_complete(store)
    assert hub.range_requests("model.bin") == [None]


def test_partial_of_another_revision_is_wiped(store, hub):
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    (partial / ".vf-revision").write_text("old-revision")
    (partial / "model.bin").write_bytes(b"x" * 1000)
    wait(store)
    assert_complete(store)
    assert hub.range_requests("model.bin") == [None]


def test_partial_never_counts_as_downloaded(store):
    partial = store.models_dir / ".partial-m"
    partial.mkdir(parents=True)
    for path, data in CONTENTS.items():
        (partial / path).write_bytes(data)
    assert store.is_downloaded("m") is False
    assert store.status("m")["downloaded"] is False


def test_incomplete_or_stale_final_dir_is_not_downloaded(store):
    final = install_model(store.models_dir, SPEC, CONTENTS)
    assert store.is_downloaded("m")
    (final / "model.bin").write_bytes(b"short")
    assert not store.is_downloaded("m")
    install_model(store.models_dir, SPEC, CONTENTS)
    (final / MANIFEST).write_text(json.dumps({"revision": "other"}))
    assert not store.is_downloaded("m")
    (final / MANIFEST).write_text("not json")
    assert not store.is_downloaded("m")


def test_redownload_replaces_stale_final_dir(store):
    final = install_model(store.models_dir, SPEC, CONTENTS)
    (final / MANIFEST).write_text(json.dumps({"revision": "other"}))
    (final / "junk.txt").write_text("old")
    wait(store)
    assert_complete(store)
    assert not (final / "junk.txt").exists()
    assert not list(store.models_dir.glob(".old-*"))


def test_checksum_mismatch_fails_and_removes_file(store, hub):
    hub.corrupt.add("model.bin")
    with pytest.raises(ServiceError) as exc:
        wait(store)
    assert exc.value.code == "download_failed"
    assert "checksum mismatch" in exc.value.message
    status = store.status("m")
    assert status["downloaded"] is False
    assert status["downloading"] is False
    assert "checksum mismatch" in status["error"]
    assert not (store.models_dir / ".partial-m" / "model.bin").exists()
    # The error is cleared when a new download starts and succeeds.
    hub.corrupt.clear()
    wait(store)
    assert store.status("m")["error"] is None


def test_http_404_is_not_retried(store, hub):
    hub.fail["model.bin"] = 404
    with pytest.raises(ServiceError) as exc:
        wait(store)
    assert "HTTP 404" in exc.value.message
    assert hub.resolves.count("model.bin") == 1


def test_http_503_is_retried_then_fails(store, hub):
    hub.fail["model.bin"] = 503
    with pytest.raises(ServiceError) as exc:
        wait(store)
    assert "HTTP 503" in exc.value.message
    assert "after 4 attempts" in exc.value.message
    assert hub.resolves.count("model.bin") == 4


def test_cut_connection_is_resumed(store, hub):
    hub.cut_once.add("model.bin")
    wait(store)
    assert_complete(store)
    ranges = hub.range_requests("model.bin")
    assert ranges[0] is None
    assert ranges[1] == f"bytes={len(CONTENTS['model.bin']) // 2}-"


def test_not_enough_disk_space(store, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(models_mod.shutil, "disk_usage", lambda _: usage(10, 10, 1000))
    with pytest.raises(ServiceError) as exc:
        wait(store)
    assert exc.value.code == "download_failed"
    assert "not enough disk space" in exc.value.message


def test_wait_ready_joins_running_download_and_can_be_stopped(store, hub):
    hub.chunk = 4 * 1024
    hub.delay_s = 0.02
    store.start_download("m")
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        store.wait_ready("m", stop)
    # The download itself goes on and finishes.
    assert wait(store) == store.models_dir / "m"
    assert len(hub.range_requests("model.bin")) == 1


def test_delete_cancels_download_and_cleans_up(store, hub):
    hub.chunk = 4 * 1024
    hub.delay_s = 0.05
    store.start_download("m")
    deadline = time.monotonic() + 10
    while not (store.models_dir / ".partial-m" / "model.bin").exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    started = time.monotonic()
    status = store.delete("m")
    assert time.monotonic() - started < 3
    assert status["downloading"] is False
    assert status["downloaded"] is False
    assert status["error"] is None
    assert not (store.models_dir / ".partial-m").exists()
    assert not (store.models_dir / "m").exists()


def test_delete_in_use_is_busy(store):
    install_model(store.models_dir, SPEC, CONTENTS)
    removed = []
    with store.in_use("m"), pytest.raises(ServiceError) as exc:
        store.delete("m", on_remove=removed.append)
    assert exc.value.code == "busy"
    assert removed == []
    assert store.is_downloaded("m")
    store.delete("m", on_remove=removed.append)
    assert removed == ["m"]
    assert not (store.models_dir / "m").exists()
    # Idempotent.
    assert store.delete("m")["downloaded"] is False


def test_cleanup_stale_keeps_partials(store):
    (store.models_dir / ".old-m-1234").mkdir(parents=True)
    (store.models_dir / ".old-m-1234" / "model.bin").write_bytes(b"x")
    (store.models_dir / ".partial-m").mkdir()
    store.cleanup_stale()
    assert not (store.models_dir / ".old-m-1234").exists()
    assert (store.models_dir / ".partial-m").exists()


def test_cleanup_stale_without_models_dir(tmp_path):
    ModelStore(tmp_path / "missing", {}, "http://127.0.0.1:9").cleanup_stale()
