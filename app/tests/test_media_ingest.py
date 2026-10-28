import asyncio
import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from vf.core import db, files, jobs, settings
from vf.core.errors import AppError
from vf.core.services import render
from vf.modules.media import cleanup, ingest

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()


async def _wait(job_id, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        row = jobs.get(job_id)
        if row["status"] in jobs.FINISHED:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {jobs.get(job_id)['status']}")


@pytest.fixture
def fake_render(monkeypatch):
    """``render.probe`` / ``render.run`` without the container: writes the poster and preview."""
    calls: list[tuple] = []
    meta = {"duration": 8.04, "has_video": True, "width": 1920, "height": 1080,
            "display_width": 1080, "display_height": 1920}

    async def probe(rel):
        calls.append(("probe", rel))
        return dict(meta)

    async def run(op, body, **kwargs):
        calls.append((op, body))
        files.abs_path(body["poster_output"]).write_bytes(b"\xff\xd8\xff\xe0poster")
        files.abs_path(body["preview_output"]).write_bytes(b"RIFF\x00\x00\x00\x00WEBPpreview")
        return {"poster": {"output": body["poster_output"]}, "preview": {"output": body["preview_output"]}}

    monkeypatch.setattr(render, "probe", probe)
    monkeypatch.setattr(render, "run", run)
    return {"calls": calls, "meta": meta}


def _video(**kwargs):
    return files.save_bytes(MP4, mime="video/mp4", name="clip.mp4", **kwargs)


def test_derived_paths():
    assert ingest.derived_paths("files/2026/10/ab.mp4") == ("files/2026/10/ab.poster.jpg",
                                                            "files/2026/10/ab.preview.webp")


async def test_video_gets_poster_preview_and_size(runner, fake_render):
    row = _video(origin="upload")
    row = files.update(row["id"], {"width": 10, "height": 10})
    job_id = ingest.enqueue_video_ingest(row["id"])
    done = await _wait(job_id)
    assert done["status"] == "done", done
    assert done["ref_type"] == "file" and done["ref_id"] == row["id"]
    fresh = files.get(row["id"])
    assert fresh["duration"] == 8.04
    assert (fresh["width"], fresh["height"]) == (1080, 1920)  # upright size of a turned phone video
    assert fresh["poster_path"].endswith(".poster.jpg") and fresh["preview_path"].endswith(".preview.webp")
    assert fresh["meta_json"]["ingest"]["status"] == "done"
    assert fresh["meta_json"]["ingest"]["attempts"] == 1
    public = files.public(fresh)
    assert public["thumb_url"] == f"/files/{row['id']}/poster"
    assert public["preview_url"] == f"/files/{row['id']}/preview"
    op, body = fake_render["calls"][1]
    assert op == "preview" and body["input"] == row["path"]
    # Deleting the video removes its poster and preview too.
    files.delete(row["id"])
    assert not files.abs_path(fresh["poster_path"]).exists()
    assert not files.abs_path(fresh["preview_path"]).exists()


async def test_video_without_picture_becomes_audio(runner, fake_render):
    fake_render["meta"].update(has_video=False, duration=3.5)
    row = _video()
    done = await _wait(ingest.enqueue_video_ingest(row["id"]))
    assert done["status"] == "done"
    fresh = files.get(row["id"])
    assert fresh["kind"] == "audio" and fresh["mime"] == "audio/mp4" and fresh["duration"] == 3.5
    assert fresh["poster_path"] is None
    assert [c[0] for c in fake_render["calls"]] == ["probe"]


async def test_audio_gets_duration_only(runner, fake_render):
    fake_render["meta"].update(has_video=False, duration=61.2)
    row = files.save_bytes(b"ID3\x04" + b"\x00" * 100, mime="audio/mpeg", name="a.mp3")
    done = await _wait(ingest.enqueue_video_ingest(row["id"]))
    assert done["status"] == "done"
    assert files.get(row["id"])["duration"] == 61.2
    assert [c[0] for c in fake_render["calls"]] == ["probe"]


async def test_images_are_not_queued(database):
    row = files.save_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, mime="image/png", name="a.png")
    assert ingest.enqueue_video_ingest(row["id"]) is None


async def test_render_down_is_recorded(runner, monkeypatch):
    async def probe(_rel):
        raise AppError("render_unavailable", 503, "render is not running")

    monkeypatch.setattr(render, "probe", probe)
    row = _video()
    done = await _wait(ingest.enqueue_video_ingest(row["id"]))
    assert done["status"] == "error" and done["error_code"] == "render_unavailable"
    state = files.get(row["id"])["meta_json"]["ingest"]
    assert state["status"] == "error" and state["error_code"] == "render_unavailable"


async def test_deleted_while_rendering(runner, monkeypatch, fake_render):
    row = _video()

    async def run(op, body, **kwargs):
        files.abs_path(body["poster_output"]).write_bytes(b"poster")
        files.abs_path(body["preview_output"]).write_bytes(b"preview")
        files.delete(row["id"])
        return {"poster": {"output": body["poster_output"]}, "preview": {"output": body["preview_output"]}}

    monkeypatch.setattr(render, "run", run)
    done = await _wait(ingest.enqueue_video_ingest(row["id"]))
    assert done["status"] == "done" and done["result_json"]["skipped"] == "deleted"
    poster, preview = ingest.derived_paths(row["path"])
    assert not files.abs_path(poster).exists() and not files.abs_path(preview).exists()


def test_sweep_picks_up_forgotten_videos(database, monkeypatch):
    queued = []
    monkeypatch.setattr(ingest.jobs, "enqueue", lambda *a, **kw: queued.append(kw["ref_id"]) or len(queued))
    old = "2026-01-01T00:00:00.000Z"
    forgotten = _video()
    db.update("files", forgotten["id"], {"created_at": old})
    fresh = _video()  # just made: its module may still be queueing it
    service = _video(service=True)
    db.update("files", service["id"], {"created_at": old})
    failed = _video()
    db.update("files", failed["id"], {"created_at": old, "meta_json": {"ingest": {
        "status": "error", "error_code": "render_failed", "attempts": 1, "at": old}}})
    retry = _video()
    db.update("files", retry["id"], {"created_at": old, "meta_json": {"ingest": {
        "status": "error", "error_code": "render_unavailable", "attempts": 1, "at": old}}})
    tired = _video()
    db.update("files", tired["id"], {"created_at": old, "meta_json": {"ingest": {
        "status": "error", "error_code": "render_unavailable", "attempts": 3, "at": old}}})

    ingest.sweep()
    assert sorted(queued) == sorted([forgotten["id"], retry["id"]])
    assert fresh["id"] not in queued and service["id"] not in queued

    queued.clear()
    settings.set("media.auto_ingest", False)
    assert ingest.sweep() == [] and queued == []


def test_sweep_skips_files_with_a_job(database):
    row = _video()
    db.update("files", row["id"], {"created_at": "2026-01-01T00:00:00.000Z"})
    jobs.enqueue(ingest.JOB_KIND, {"file_id": row["id"]}, ref_type="file", ref_id=row["id"])
    db.update("files", row["id"], {"meta_json": {}})
    assert ingest.sweep() == []


# --- cleanup -------------------------------------------------------------------------------


def _age(row, hours):
    stamp = (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    db.update("files", row["id"], {"created_at": stamp})
    past = time.time() - hours * 3600
    os.utime(files.abs_path(row["path"]), (past, past))


def test_cleanup_never_touches_files_of_the_person(database, cfg):
    used: set[int] = set()

    def provider(file_id):
        return [{"type": "editor", "id": 1, "title": "Project"}] if file_id in used else []

    files._usage_providers.append(provider)
    try:
        upload = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="u.mp3", origin="upload")
        result = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="r.mp3")
        old_service = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="s.mp3", service=True)
        used_service = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="s2.mp3", service=True)
        new_service = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="s3.mp3", service=True)
        for row in (upload, result, old_service, used_service):
            _age(row, 48)
        used.add(used_service["id"])

        tmp = cfg.data_dir / "cache" / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        old_tmp, new_tmp = tmp / "old.part", tmp / "new.part"
        old_tmp.write_bytes(b"x")
        new_tmp.write_bytes(b"y")
        past = time.time() - 48 * 3600
        os.utime(old_tmp, (past, past))

        video = _video(origin="upload")
        poster, preview = ingest.derived_paths(video["path"])
        files.abs_path(poster).write_bytes(b"kept: the video exists")
        orphan = files.abs_path("files/2026/01/deadbeef.poster.jpg")
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"orphan")
        os.utime(orphan, (past, past))
        os.utime(files.abs_path(poster), (past, past))
        thumbs = cfg.data_dir / "cache" / "thumbs"
        (thumbs / "999999").mkdir(parents=True)
        (thumbs / str(upload["id"])).mkdir(parents=True)

        report = cleanup.run_cleanup()
    finally:
        files._usage_providers.remove(provider)

    assert report == {"service_files": 1, "service_files_in_use": 1, "tmp_files": 1, "orphan_previews": 1,
                      "orphan_thumbs": 1}
    for row in (upload, result, used_service, new_service, video):
        assert db.get("files", row["id"]) is not None
        assert files.abs_path(row["path"]).exists()
    assert db.get("files", old_service["id"]) is None
    assert not files.abs_path(old_service["path"]).exists()
    assert not old_tmp.exists() and new_tmp.exists()
    assert not orphan.exists() and files.abs_path(poster).exists()
    assert not (thumbs / "999999").exists() and (thumbs / str(upload["id"])).exists()


def test_cleanup_window_setting(database):
    row = files.save_bytes(b"ID3" + b"\x00" * 10, mime="audio/mpeg", name="s.mp3", service=True)
    _age(row, 30)
    settings.set("media.cleanup_service_hours", 72)
    assert cleanup.run_cleanup()["service_files"] == 0
    settings.set("media.cleanup_service_hours", 24)
    assert cleanup.run_cleanup()["service_files"] == 1
