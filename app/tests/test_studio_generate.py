"""Module 04 (image studio): drawing frames through the gateway (stub mode), the spend
journal, the series pilot, corrections of one object, rollback, failures, stuck frames."""

import asyncio
import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from vf.core import db, files, jobs, settings
from vf.core.google import gateway, journal
from vf.core.google.limiter import limiter
from vf.modules import studio
from vf.modules.brand import subjects
from vf.modules.studio import generate
from vf.modules.studio import works as W
from vf.modules.studio.common import BUSY


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()


def png(color=(20, 120, 200), size=(64, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def size_of(file_id: int) -> tuple[int, int]:
    with Image.open(io.BytesIO(files.read_bytes(file_id))) as im:
        return im.size


async def settled(*frame_ids: int, timeout: float = 15.0) -> list[dict]:
    for _ in range(int(timeout / 0.02)):
        rows = [db.get("frames", fid) for fid in frame_ids]
        if all(r["status"] not in BUSY for r in rows):
            return [W.frame_public(r) for r in rows]
        await asyncio.sleep(0.02)
    raise AssertionError(f"frames still busy: {[db.get('frames', f)['status'] for f in frame_ids]}")


def calls(purpose: str) -> list[dict]:
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


async def test_series_with_reference_and_subject(runner):
    ref = files.save_bytes(png((200, 30, 30)), mime="image/png", name="ref.png", origin="upload")
    loaf = subjects.create_subject("Loaf", kind="product", description="Round rye loaf")
    subjects.add_photo_upload(loaf["id"], png((90, 60, 30)), filename="loaf.png")
    work = studio.create_work({"title": "Bakery", "aspect": "4:5", "frame_count": 4, "settings": {
        "series": True, "ideas_brief": "Fresh bread on a wooden table", "references": [ref["id"]],
        "subjects": [loaf["id"]]}})
    pilot_id, *rest = (f["id"] for f in work["frames"])

    out = studio.start_all(work["id"])
    assert out["queued"] == [pilot_id]
    assert [s["reason"] for s in out["skipped"]] == ["pilot_not_ready"] * 3
    (pilot,) = await settled(pilot_id)
    assert pilot["status"] == "done", pilot["error_text"]
    assert size_of(pilot["file_id"]) == (1080, 1350)          # the configured 4:5 size, not the model's
    roles = {a["role"] for a in pilot["attachments"]}
    assert {"reference", "subject"} <= roles and "anchor" not in roles
    assert "Fresh bread" in pilot["prompt_text"]
    assert db.get("image_works", work["id"])["status"] == "active"

    out = studio.accept_pilot(work["id"])
    assert sorted(out["queued"]) == sorted(rest) and out["work"]["pilot"]["accepted"] is True
    for frame in await settled(*rest):
        assert frame["status"] == "done", frame["error_text"]
        anchor = [a for a in frame["attachments"] if a["role"] == "anchor"]
        assert len(anchor) == 1 and anchor[0]["file_id"] == pilot["file_id"]

    # Every picture is in the spend journal with its price, the prompt and both refs.
    drawn = calls("frame")
    assert len(drawn) == 4
    for call in drawn:
        assert call["status"] == "success" and call["cost_usd"] > 0 and call["kind"] == "image"
        assert call["prompt_code"] == "STUDIO_FRAME" and call["prompt_version"] == 1
        assert ("work", work["id"]) in refs_of(call["id"])
    work = studio.get_work(work["id"])
    for frame in work["frames"]:
        assert frame["cost_usd"] == journal.cost_of("frame", frame["id"]) > 0
        (version,) = frame["versions"]
        assert version["mode"] == "full" and version["cost_usd"] == frame["cost_usd"]
    assert work["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in drawn), abs=1e-6)

    data, name = studio.build_zip(work["id"])
    assert name.startswith("bakery-")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["01.png", "02.png", "03.png", "04.png"]


async def test_find_objects_edit_one_and_roll_back(runner):
    work = studio.create_work({"title": "Cup", "aspect": "1:1", "frame_count": 1,
                               "settings": {"ideas_brief": "A cup on a table"}})
    fid = work["frames"][0]["id"]
    studio.start_frame(fid)
    (frame,) = await settled(fid)
    first_file = frame["file_id"]

    found = await studio.find_objects(fid)
    assert found["cached"] is False and found["objects"]["items"]
    (look,) = calls("regions")
    assert look["status"] == "success" and look["cost_usd"] > 0
    assert refs_of(look["id"]) == {("work", work["id"]), ("frame", fid)}
    again = await studio.find_objects(fid)
    assert again["cached"] is True and again["objects"]["items"] == found["objects"]["items"]
    assert len(calls("regions")) == 1                     # the second look is free
    est = studio.estimate({"action": "find_objects", "frame_id": fid})
    assert est["usd"] == 0 and est["items"][0]["cached"] is True

    target = found["objects"]["items"][0]
    studio.start_edit(fid, "make the cup red", {"id": target["id"]})
    (frame,) = await settled(fid)
    assert frame["status"] == "done", frame["error_text"]
    assert frame["file_id"] != first_file and len(frame["versions"]) == 2
    assert frame["versions"][-1]["mode"] == "edit"
    assert frame["objects"] is None                                   # found on the old picture
    (edit,) = calls("frame_edit")
    sent = edit["attachments_json"]
    assert len(sent) == 2 and sent[0]["file_id"] == first_file and sent[1]["file_id"] is None
    assert "make the cup red" in edit["prompt_text"]
    assert [a["role"] for a in frame["attachments"]] == ["edit_base", "edit_marker"]

    before = db.fetch_value("SELECT COUNT(*) FROM ai_calls")
    frame = studio.restore_version(fid, 0)
    assert frame["file_id"] == first_file
    assert frame["objects"]["items"] == found["objects"]["items"]     # come back with the picture
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls") == before    # rollback is free


@pytest.mark.parametrize(("marker", "code"), [
    ("[stub:blocked]", "safety_blocked"),
    ("[stub:refused]", "refused"),
    ("[stub:error=server_error]", "server_error"),
])
async def test_failures_are_shown_and_journaled(runner, marker, code):
    work = studio.create_work({"title": "Oops", "frame_count": 1})
    fid = work["frames"][0]["id"]
    studio.update_frame(fid, {"brief": f"Bread {marker}"})
    studio.start_frame(fid)
    (frame,) = await settled(fid)
    assert frame["status"] == "error" and frame["error_code"] == code and frame["error_text"]
    assert frame["file_id"] is None and frame["versions"] == []
    assert calls("frame") and all(("frame", fid) in refs_of(c["id"]) for c in calls("frame"))


async def test_google_asks_to_wait(runner, monkeypatch):
    work = studio.create_work({"title": "Busy", "frame_count": 1})
    fid = work["frames"][0]["id"]
    studio.update_frame(fid, {"brief": "Bread [stub:error=rate_limited]"})
    seen: list[bool] = []

    async def pause(seconds, cancel=None):
        seen.append(W.frame_public(W.frame_row(fid))["waiting"])

    monkeypatch.setattr(gateway, "_sleep", pause)
    studio.start_frame(fid)
    (frame,) = await settled(fid)
    assert seen and all(seen)
    assert frame["status"] == "error" and frame["error_code"] == "rate_limited" and frame["waiting"] is False


async def test_cancel_while_drawing_keeps_the_old_picture(runner, monkeypatch):
    work = studio.create_work({"title": "Stop", "frame_count": 1, "settings": {"ideas_brief": "Bread"}})
    fid = work["frames"][0]["id"]
    old = files.save_bytes(png(), mime="image/png", name="old.png", origin="upload")
    studio.pick_picture(fid, old["id"])
    monkeypatch.setenv("VF_STUB_DELAY", "5")
    studio.start_frame(fid)
    for _ in range(250):
        if db.get("frames", fid)["status"] == "drawing":
            break
        await asyncio.sleep(0.02)
    studio.cancel_frame(fid)
    (frame,) = await settled(fid)
    assert frame["status"] == "done" and frame["file_id"] == old["id"]
    for _ in range(250):
        if jobs.get(frame["job_id"])["status"] in jobs.FINISHED:
            break
        await asyncio.sleep(0.02)
    assert jobs.get(frame["job_id"])["status"] == "cancelled"


def test_frames_left_behind_are_put_in_order(database):
    work = studio.create_work({"title": "Left", "frame_count": 3, "settings": {"ideas_brief": "Bread"}})
    stuck, failed, gone = (f["id"] for f in work["frames"])
    for fid in (stuck, failed, gone):
        studio.start_frame(fid)

    # Drawing for too long: the job is stopped and the frame says so.
    old = (datetime.now(UTC) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    db.update("frames", stuck, {"status": "drawing", "drawing_since": old})
    # The job ended with an error the frame did not hear about.
    job_id = db.get("frames", failed)["job_id"]
    db.update("jobs", job_id, {"status": "error", "error_code": "server_error", "error": "boom"})
    # The job row is gone.
    db.update("frames", gone, {"job_id": None})

    assert studio.sweep() == 3
    rows = {fid: db.get("frames", fid) for fid in (stuck, failed, gone)}
    assert rows[stuck]["status"] == "error" and rows[stuck]["error_code"] == "stuck"
    assert jobs.get(rows[stuck]["job_id"])["status"] == "cancelled"
    assert rows[failed]["status"] == "error" and rows[failed]["error_code"] == "server_error"
    assert rows[failed]["error_text"] == "boom"
    assert rows[gone]["status"] == "empty"
    assert studio.sweep() == 0


def test_settle_on_read(database):
    work = studio.create_work({"title": "Read", "frame_count": 1, "settings": {"ideas_brief": "Bread"}})
    fid = work["frames"][0]["id"]
    job_id = studio.start_frame(fid)["job_id"]
    db.update("jobs", job_id, {"status": "interrupted"})
    assert generate.settle(db.get("frames", fid)) is True
    frame = db.get("frames", fid)
    assert frame["status"] == "error" and frame["error_code"] == "interrupted"
