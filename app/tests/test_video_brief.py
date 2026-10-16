"""Module 11 (video), the helpers before a take: «Write it for me» (the market read
cached by niche + platform, the previous text kept, the camera suggestion) and the
storyboard sheet (the text shown before pressing, drawing, the user's own sheet,
attaching it to the take)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, prompts, settings
from vf.core.google import GoogleCallError
from vf.core.google.limiter import limiter
from vf.modules import library, video
from vf.modules.video import brief, catalog, runs, storyboard


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


@pytest.fixture
def api(cfg):
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as c:
        yield c


def err(r) -> str:
    return r.json()["error"]["code"]


def stored_png(color=(20, 120, 200)) -> dict:
    buf = io.BytesIO()
    Image.new("RGB", (64, 80), color).save(buf, "PNG")
    return files.save_bytes(buf.getvalue(), mime="image/png", name="pic.png", origin="upload")


def calls(purpose: str) -> list[dict]:
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def veo_with_references() -> dict:
    for m in catalog.video_models():
        if m["api"] == "veo" and catalog.max_references(m) > 0:
            return m
    pytest.skip("no video model with references")


# ── «Write it for me» ───────────────────────────────────────────────────────


async def test_write_brief_researches_once_and_keeps_the_old_text():
    run = video.create_run({"niche": "Coffee shop", "platform": "TikTok", "duration": 8})
    est = brief.estimate_write(run["id"])
    assert est["research"] and not est["research_cached"] and est["research_usd"] > 0 and est["brief_usd"] > 0
    assert est["total_usd"] == pytest.approx(est["brief_usd"] + est["research_usd"], abs=1e-4)

    out = await brief.write_brief(run["id"])
    assert out["brief"] and out["cost_usd"] > 0 and out["research_error"] is None
    assert out["camera_move_suggested"] is None                       # the stub names no real move
    (research,) = calls("video_research")
    (written,) = calls("video_brief")
    assert research["prompt_code"] == "video.research" and written["prompt_code"] == "video.brief"
    assert "NICHE: Coffee shop" in written["prompt_text"] and "CAMERA MOVES:" in written["prompt_text"]
    assert db.fetch_value("SELECT COUNT(*) FROM video_research") == 1
    meta = runs.get_run(run["id"])["brief_meta_json"]
    assert meta["seconds"] == 8 and meta["researched"] is True and meta["replaced"] is None

    # Same niche, other run: the read comes from the cache (free); the text box is not empty → ask first.
    other = video.create_run({"niche": "  coffee   SHOP ", "platform": "tiktok", "brief": "My idea"})
    est = brief.estimate_write(other["id"])
    assert est["research_cached"] and est["research_usd"] == 0 and est["brief_exists"] is True
    with pytest.raises(Exception) as exists:
        await brief.write_brief(other["id"])
    assert exists.value.code == "video_brief_exists"
    await brief.write_brief(other["id"], force=True)
    assert len(calls("video_research")) == 1 and len(calls("video_brief")) == 2
    assert "CONCEPT:\nMy idea" in calls("video_brief")[-1]["prompt_text"]

    # The old text can be brought back, and back again.
    other_run = runs.get_run(other["id"])
    written_text = other_run["brief"]
    assert other_run["brief_meta_json"]["replaced"] == "My idea"
    assert brief.restore_previous(other["id"])["brief"] == "My idea"
    assert brief.restore_previous(other["id"])["brief"] == written_text


async def test_old_research_is_paid_again_and_cache_can_be_off():
    run = video.create_run({"niche": "Bikes"})
    await brief.write_brief(run["id"])
    db.execute("UPDATE video_research SET created_at = '2000-01-01T00:00:00.000Z'")
    runs.update_run_state(run["id"], brief="")
    await brief.write_brief(run["id"])
    assert len(calls("video_research")) == 2

    settings.set("video.research_cache_days", 0)
    assert brief.estimate_write(run["id"])["research_cached"] is False


async def test_write_brief_refusals_and_without_research(api):
    run = video.create_run({})
    r = api.post(f"/api/video/runs/{run['id']}/brief/write", json={})
    assert r.status_code == 400 and err(r) == "video_niche_empty"
    r = api.post(f"/api/video/runs/{run['id']}/brief/write", json={"research": False})
    assert r.status_code == 400 and err(r) == "video_niche_empty"   # nothing to write from
    r = api.post(f"/api/video/runs/{run['id']}/brief/restore")
    assert r.status_code == 409 and err(r) == "video_no_previous_brief"
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls") == 0

    pic = stored_png()
    api.patch(f"/api/video/runs/{run['id']}", json={"first_frame_id": pic["id"], "duration": 4})
    est = api.get(f"/api/video/runs/{run['id']}/brief/estimate", params={"research": False}).json()
    assert est["research_usd"] == 0 and est["photo"] is True and est["niche_needed"] is False
    out = api.post(f"/api/video/runs/{run['id']}/brief/write", json={"research": False}).json()
    assert out["run"]["brief"] == out["result"]["brief"]
    (row,) = calls("video_brief")
    assert len(row["attachments_json"]) == 1 and calls("video_research") == []   # the opening frame went along

    # The length changed after writing → the screen offers "rewrite for N seconds".
    api.patch(f"/api/video/runs/{run['id']}", json={"duration": 8})
    est = api.get(f"/api/video/runs/{run['id']}/brief/estimate").json()
    snapped = runs.get_run(run["id"])["duration"]
    assert est["written_for_seconds"] == 4 and est["duration_changed"] is (snapped != 4)


async def test_failed_research_does_not_stop_the_text(monkeypatch):
    real = prompts.run_prompt

    async def research_fails(code, *args, **kwargs):
        if code == brief.RESEARCH_PROMPT:
            raise GoogleCallError("server_error", "500 backend error")
        return await real(code, *args, **kwargs)

    monkeypatch.setattr(prompts, "run_prompt", research_fails)
    run = video.create_run({"niche": "Cars"})
    out = await brief.write_brief(run["id"])
    assert out["research_error"] == "server_error" and out["brief"]
    assert runs.get_run(run["id"])["brief_meta_json"]["research_error"] == "server_error"
    assert db.fetch_value("SELECT COUNT(*) FROM video_research") == 0


def test_camera_suggestion_is_one_click(api):
    run = video.create_run({"brief": "A train"})
    r = api.post(f"/api/video/runs/{run['id']}/brief/camera")
    assert r.status_code == 400 and err(r) == "video_camera_unknown"
    code = catalog.camera_moves()[0]["code"]
    runs.update_run_state(run["id"], brief_meta_json={"camera_move_suggested": code})
    out = api.post(f"/api/video/runs/{run['id']}/brief/camera").json()
    assert out["camera_move"] == code


# ── storyboard ──────────────────────────────────────────────────────────────


def test_storyboard_text_is_shown_before_pressing(api):
    pic = stored_png()
    run = video.create_run({"brief": "A dog runs on the beach", "duration": 8, "first_frame_id": pic["id"]})
    out = api.post(f"/api/video/runs/{run['id']}/storyboard/preview", json={}).json()
    assert out["ready"] and out["panels"] == 4 and out["auto_panels"] is True
    assert out["shot"] == out["default_shot"] == "A dog runs on the beach"
    assert "A dog runs on the beach" in out["text"] and "Subject 1" in out["text"] and out["estimate_usd"] > 0
    out = api.post(f"/api/video/runs/{run['id']}/storyboard/preview", json={"shot": "Only the dog", "panels": 50}).json()
    assert out["panels"] == storyboard.MAX_PANELS and out["shot"] == "Only the dog"
    empty = video.create_run({})
    out = api.post(f"/api/video/runs/{empty['id']}/storyboard/preview", json={}).json()
    assert out["ready"] is False and out["refusal"] == "video_brief_empty"
    r = api.post(f"/api/video/runs/{empty['id']}/storyboard", json={})
    assert r.status_code == 400 and err(r) == "video_brief_empty"
    assert storyboard.timecodes(8, 4) == "01 0:00–0:02, 02 0:02–0:04, 03 0:04–0:06, 04 0:06–0:08"
    assert storyboard.auto_panels(4) == 3 and storyboard.auto_panels(30) == 8


async def test_storyboard_is_drawn_attached_and_travels_with_the_take(api):
    veo = veo_with_references()
    run = video.create_run({"brief": "A dog runs", "model_id": veo["id"]})
    out = api.post(f"/api/video/runs/{run['id']}/storyboard", json={"shot": "The dog jumps"}).json()
    sb = out["storyboard"]
    assert sb["attached"] is True and sb["own"] is False and sb["shot"] == "The dog jumps"
    (row,) = calls("video_storyboard")
    assert row["prompt_code"] == storyboard.TAKE_LAYER and "The dog jumps" in row["prompt_text"]
    sheet = files.get(sb["file_id"])
    assert sheet["kind"] == "image" and sheet["is_service"] == 0

    take = out["take"]
    note = library.render_layer(runs.STORYBOARD_NOTE, {}).strip()
    assert take["storyboard"] is True and take["references_sent"] == 1
    assert take["prompt"].startswith("A dog runs") and take["prompt"].endswith(note)

    out = api.post(f"/api/video/runs/{run['id']}/storyboard/attach", json={"attached": False}).json()
    assert out["take"]["storyboard"] is False and out["take"]["prompt"] == "A dog runs"

    own = stored_png((200, 0, 0))
    out = api.post(f"/api/video/runs/{run['id']}/storyboard/pick", json={"file_id": own["id"]}).json()
    assert out["storyboard"]["own"] is True and out["storyboard"]["attached"] is True
    assert out["take"]["storyboard"] is True and len(calls("video_storyboard")) == 1   # own sheet is free

    assert api.delete(f"/api/video/runs/{run['id']}/storyboard").json()["storyboard"] in (None, {})
    r = api.post(f"/api/video/runs/{run['id']}/storyboard/attach", json={"attached": True})
    assert r.status_code == 409 and err(r) == "video_storyboard_none"
    assert files.get(sb["file_id"])                                      # the drawn sheet stays in the library
