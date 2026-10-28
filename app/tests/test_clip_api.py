"""Module 12: clip projects over HTTP and the export job (render is faked)."""

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, jobs
from vf.core.errors import AppError
from vf.core.services import render
from vf.modules.clip import export, projects

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def fake_render(monkeypatch):
    """``render.probe`` / ``render.run`` without the container; every output is written."""
    calls: list[tuple] = []
    meta = {"duration": 10.0, "has_video": True, "has_audio": True, "width": 1920, "height": 1080}
    written: dict[str, dict] = {}  # outputs of render answer the probe with their own size

    async def probe(rel):
        calls.append(("probe", rel))
        return {**meta, **written.get(rel, {})}

    async def run(op, body, **kwargs):
        calls.append((op, body))
        if op == "preview":  # media ingest of the exported files
            files.abs_path(body["poster_output"]).write_bytes(b"\xff\xd8\xff\xe0poster")
            files.abs_path(body["preview_output"]).write_bytes(b"RIFF\x00\x00\x00\x00WEBPpreview")
            return {"poster": {"output": body["poster_output"]}, "preview": {"output": body["preview_output"]}}
        if op == "split":
            outs = []
            for rel in body["outputs"]:
                files.abs_path(rel).write_bytes(MP4)
                written[rel] = {"duration": 2.0, "width": 1080, "height": 1920}
                outs.append({"output": rel, "meta": written[rel]})
            return {"outputs": outs}
        if op == "compose":
            files.abs_path(body["output"]).write_bytes(MP4)
            written[body["output"]] = {"duration": 6.0, "width": 1080, "height": 1920}
            return {"output": body["output"], "meta": written[body["output"]]}
        raise AssertionError(f"unexpected render op {op}")

    monkeypatch.setattr(render, "probe", probe)
    monkeypatch.setattr(render, "run", run)
    return {"calls": calls, "meta": meta}


@pytest.fixture
def api(cfg, fake_render):
    """The app without the job runner, so queued jobs stay queued."""
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as test_client:
        yield test_client


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


def _video(**kwargs):
    return files.save_bytes(MP4, mime="video/mp4", name="holiday.mp4", **kwargs)


# ── projects over HTTP ──────────────────────────────────────────────────────

def test_open_reuses_the_newest_project(api, fake_render):
    video = _video()
    first = api.post("/api/clip/projects", json={"file_id": video["id"]}).json()
    assert first["title"] == "holiday" and first["status"] == "draft"
    assert first["source"] == {"duration": 10.0, "width": 1920, "height": 1080, "has_audio": True}
    assert first["source_file"]["id"] == video["id"]
    again = api.post("/api/clip/projects", json={"file_id": video["id"]}).json()
    assert again["id"] == first["id"]
    other = api.post("/api/clip/projects", json={"file_id": video["id"], "new": True, "title": "B"}).json()
    assert other["id"] != first["id"] and other["title"] == "B"
    listed = api.get("/api/clip/projects", params={"file_id": video["id"]}).json()["items"]
    assert [p["id"] for p in listed] == [other["id"], first["id"]]


def test_open_refuses_what_is_not_a_video(api):
    image = files.save_bytes(png(), mime="image/png", name="a.png")
    res = api.post("/api/clip/projects", json={"file_id": image["id"]})
    assert res.status_code == 400 and res.json()["error"]["code"] == "clip_not_video"
    assert api.post("/api/clip/projects", json={"file_id": 999999}).status_code == 404
    assert api.post("/api/clip/projects", json={}).status_code == 400


def test_open_without_picture(api, fake_render):
    fake_render["meta"]["has_video"] = False
    res = api.post("/api/clip/projects", json={"file_id": _video()["id"]})
    assert res.status_code == 400 and res.json()["error"]["code"] == "clip_not_video"


def test_open_without_render_still_works(api, monkeypatch):
    async def probe(_rel):
        raise AppError("render_unavailable", 503, "render is not running")

    monkeypatch.setattr(render, "probe", probe)
    project = api.post("/api/clip/projects", json={"file_id": _video()["id"]}).json()
    assert project["source"]["duration"] is None


def test_save_state_title_and_usage(api):
    video = _video()
    image = files.save_bytes(png(), mime="image/png", name="logo.png")
    project = api.post("/api/clip/projects", json={"file_id": video["id"]}).json()
    url = f"/api/clip/projects/{project['id']}"

    bad = api.patch(url, json={"state": {"layers": [{"type": "image", "file_id": 999999}]}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "clip_file_missing"
    wrong = api.patch(url, json={"state": {"audio": {"tracks": [{"file_id": image["id"]}]}}})
    assert wrong.status_code == 400

    state = {"removed": [[2, 3]], "layers": [{"type": "image", "file_id": image["id"], "x": 0.8}],
             "subtitles": {"enabled": True, "words": [{"text": "hi", "start": 1, "end": 1.5}]}}
    saved = api.patch(url, json={"state": state, "title": "  Trip  "}).json()
    assert saved["title"] == "Trip"
    assert saved["state"]["removed"] == [[2.0, 3.0]] and saved["state"]["layers"][0]["x"] == 0.8
    assert api.get(url).json()["state"] == saved["state"]

    empty = api.patch(url, json={"title": "   "})
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "clip_title_empty"

    uses = files.usages(image["id"])
    assert {"type": "project", "id": project["id"], "title": "Trip", "url": f"/clip/{project['id']}"} in uses
    assert any(u["type"] == "project" for u in files.usages(video["id"]))
    with pytest.raises(AppError):
        files.delete(image["id"])  # in use by the clip


def test_presets_endpoint(api):
    items = api.get("/api/clip/presets").json()["items"]
    assert [p["code"] for p in items] == ["clean", "boxed", "pop", "brand"]
    assert items[0]["bold"] is True


def test_brand_snapshot(api):
    from vf.modules.brand import kits

    kit = kits.create_kit("Shop", colors=[{"hex": "#112233"}])
    project = api.post("/api/clip/projects", json={"file_id": _video()["id"]}).json()
    url = f"/api/clip/projects/{project['id']}/brand"
    res = api.put(url, json={"refresh": True})
    assert res.status_code == 400 and res.json()["error"]["code"] == "clip_no_brand"
    withkit = api.put(url, json={"kit_id": kit["id"]}).json()
    assert withkit["brand"]["kit_id"] == kit["id"] and withkit["brand_changed"] is False
    kits.update_kit(kit["id"], colors=[{"hex": "#445566"}])
    assert api.get(f"/api/clip/projects/{project['id']}").json()["brand_changed"] is True
    fresh = api.put(url, json={"refresh": True}).json()
    assert fresh["brand_changed"] is False
    assert api.put(url, json={"kit_id": None}).json()["brand"] is None


def test_export_checks_before_queueing(api):
    project = api.post("/api/clip/projects", json={"file_id": _video()["id"]}).json()
    url = f"/api/clip/projects/{project['id']}"
    api.patch(url, json={"state": {"removed": [[0, 10]]}})
    res = api.post(f"{url}/export", json={})
    assert res.status_code == 400 and res.json()["error"]["code"] == "clip_empty"
    removed = [[i * 0.3 + 0.1, i * 0.3 + 0.25] for i in range(30)]  # 31 pieces are left
    api.patch(url, json={"state": {"removed": removed}})
    res = api.post(f"{url}/export", json={})
    assert res.status_code == 400 and res.json()["error"]["code"] == "clip_too_many_pieces"

    api.patch(url, json={"state": {"cuts": [4], "crop": {"aspect": "9:16"}}})
    started = api.post(f"{url}/export", json={"parts": True}).json()
    assert started["files"] == 2 and (started["width"], started["height"]) == (1080, 1920)
    job = jobs.get(started["job_id"])
    assert job["kind"] == export.JOB_KIND and job["ref_type"] == "clip" and job["ref_id"] == project["id"]
    listed = api.get(f"{url}/jobs").json()["items"]
    assert [j["id"] for j in listed] == [started["job_id"]]


def test_newer_preview_stops_the_older_one(api):
    project = api.post("/api/clip/projects", json={"file_id": _video()["id"]}).json()
    url = f"/api/clip/projects/{project['id']}/preview"
    first = api.post(url).json()["job_id"]
    second = api.post(url).json()["job_id"]
    assert jobs.get(first)["status"] == "cancelled"
    assert jobs.get(second)["status"] == "queued" and jobs.get(second)["kind"] == export.PREVIEW_KIND


def test_delete_project_keeps_the_source(api):
    video = _video()
    project = api.post("/api/clip/projects", json={"file_id": video["id"]}).json()
    assert api.delete(f"/api/clip/projects/{project['id']}").json() == {"ok": True}
    assert api.get(f"/api/clip/projects/{project['id']}").status_code == 404
    assert files.get(video["id"])["id"] == video["id"]


# ── export job ──────────────────────────────────────────────────────────────

async def _project(state: dict | None = None) -> dict:
    video = _video()
    files.update(video["id"], {"duration": 10.0, "width": 1920, "height": 1080})
    project = await projects.open_project(video["id"])
    if state is not None:
        project = projects.update_project(project["id"], state=state)
    return project


async def test_export_one_piece(runner, fake_render):
    project = await _project({"trim": {"start": 1, "end": 7}, "crop": {"aspect": "9:16", "mode": "blur"},
                              "layers": [{"type": "text", "text": "Hello", "start": 0}]})
    job = await _wait(export.enqueue(project["id"], title=project["title"]))
    assert job["status"] == "done", job
    compose = [c[1] for c in fake_render["calls"] if c[0] == "compose"]
    assert len(compose) == 1
    body = compose[0]
    assert body["trim"] == {"start": 1.0, "end": 7.0}
    assert body["crop"] == {"aspect": "9:16", "mode": "blur"}
    assert "Hello" in body["burn"]["subtitles_ass"]
    assert "mix" not in body  # the sound stays as it is
    file_id = job["result_json"]["file_ids"][0]
    row = files.get(file_id)
    assert row["source_type"] == "clip_export" and row["source_id"] == project["id"]
    assert row["origin"] == "derived" and (row["width"], row["height"]) == (1080, 1920)
    fresh = projects.project_dict(db.get("clip_projects", project["id"]))
    assert fresh["status"] == "exported" and fresh["exports_count"] == 1
    assert projects.list_exports(project["id"])[0]["file"]["id"] == file_id
    # the source is never touched and nothing is left in the scratch folder
    assert files.abs_path(files.get(project["file_id"])["path"]).read_bytes() == MP4
    assert not any(files.abs_path("cache/tmp").glob("*.mp4"))


async def test_export_with_removed_piece_and_parts(runner, fake_render):
    music = files.save_bytes(b"ID3\x04" + b"\x00" * 100, mime="audio/mpeg", name="song.mp3")
    project = await _project({
        "removed": [[3, 5]], "cuts": [6],
        "audio": {"original_volume": 0.5, "tracks": [{"file_id": music["id"], "role": "music", "duck": True}]},
    })
    job = await _wait(export.enqueue(project["id"], parts=True, title=project["title"]))
    assert job["status"] == "done", job
    ops = [c[0] for c in fake_render["calls"] if c[0] in ("split", "compose")]
    assert ops == ["split", "compose", "split"]
    first_split, compose, parts = [c[1] for c in fake_render["calls"] if c[0] in ("split", "compose")]
    assert first_split["at"] == [3.0, 5.0]
    assert len(compose["concat"]["inputs"]) == 2 and compose["concat"]["transition"] == "cut"
    assert compose["mix"]["original_volume"] == 0.5
    assert compose["mix"]["tracks"][0]["duck"] is False  # nothing to duck under without a voice track
    assert parts["at"] == [4.0]  # the split mark at 6 s is at 4 s after the cut
    ids = job["result_json"]["file_ids"]
    assert len(ids) == 2
    assert [files.get(i)["title"] for i in ids] == ["holiday (1/2)", "holiday (2/2)"]
    rows = db.fetch_all("SELECT part_index, part_count FROM video_exports WHERE project_id = ? ORDER BY id",
                        (project["id"],))
    assert [(r["part_index"], r["part_count"]) for r in rows] == [(0, 2), (1, 2)]


async def test_volume_only_change_mixes_a_muted_copy(runner, fake_render):
    project = await _project({"audio": {"original_volume": 2.0}})
    job = await _wait(export.enqueue(project["id"]))
    assert job["status"] == "done", job
    body = next(c[1] for c in fake_render["calls"] if c[0] == "compose")
    assert body["mix"]["original_volume"] == 2.0
    assert body["mix"]["tracks"] == [{"input": files.get(project["file_id"])["path"], "role": "sfx", "volume": 0.0}]


async def test_mute_original(runner, fake_render):
    project = await _project({"audio": {"keep_original": False}})
    job = await _wait(export.enqueue(project["id"]))
    body = next(c[1] for c in fake_render["calls"] if c[0] == "compose")
    assert job["status"] == "done" and body["mix"]["keep_original_audio"] is False


async def test_preview_replaces_the_old_one(runner, fake_render):
    project = await _project({"crop": {"aspect": "16:9"}})
    first = await _wait(export.enqueue(project["id"], preview=True))
    assert first["status"] == "done", first
    body = next(c[1] for c in fake_render["calls"] if c[0] == "compose")
    assert body["crop"] == {"width": 960, "height": 540, "mode": "cover"}
    old = db.get("clip_projects", project["id"])["preview_file_id"]
    assert files.get(old)["source_type"] == "clip_preview"
    second = await _wait(export.enqueue(project["id"], preview=True))
    assert second["status"] == "done"
    new = db.get("clip_projects", project["id"])["preview_file_id"]
    assert new != old and db.get("files", old) is None
    assert projects.list_exports(project["id"]) == []  # a preview is not an export


async def test_render_error_leaves_nothing(runner, fake_render, monkeypatch):
    project = await _project({"removed": [[3, 5]]})

    async def broken(op, body, **kwargs):
        if op == "split":
            for rel in body["outputs"]:
                files.abs_path(rel).write_bytes(MP4)
            return {"outputs": [{"output": o} for o in body["outputs"]]}
        files.abs_path(body["output"]).write_bytes(b"half")
        raise AppError("render_failed", 502, "ffmpeg said no")

    monkeypatch.setattr(render, "run", broken)
    before = db.fetch_value("SELECT COUNT(*) FROM files", (), 0)
    job = await _wait(export.enqueue(project["id"]))
    assert job["status"] == "error" and job["error_code"] == "render_failed"
    assert db.fetch_value("SELECT COUNT(*) FROM files", (), 0) == before
    assert not any(files.abs_path("cache/tmp").glob("*.mp4"))
    assert not [p for p in files.abs_path("files").rglob("*.mp4") if p.read_bytes() == b"half"]


async def test_export_of_deleted_project_is_skipped(runner, fake_render):
    project = await _project()
    job_id = export.enqueue(project["id"])
    projects.delete_project(project["id"])
    job = await _wait(job_id)
    assert job["status"] == "done" and job["result_json"]["skipped"] == "deleted"
