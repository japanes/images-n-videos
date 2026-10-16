"""Module 11 (video): runs, the settings form, refusals before money, the take preview,
the catalogue routes, media usages and journal links. No job runner here: a started
take stays queued and nothing is paid."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, models_registry
from vf.modules import video
from vf.modules.video import catalog, runs


def png(color=(20, 120, 200), size=(64, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def stored_png(color=(20, 120, 200)) -> dict:
    return files.save_bytes(png(color), mime="image/png", name="pic.png", origin="upload")


def video_model(api: str, *, refs: bool = False, four_k: bool = False) -> dict:
    """A video model of this kind from the registry (ids live only in the seed)."""
    for m in catalog.video_models():
        info = catalog.model_info(m)
        if m["api"] == api and (not refs or info["max_references"] > 0) and (not four_k or "4k" in info["resolutions"]):
            return m
    pytest.skip(f"no {api} model with refs={refs} four_k={four_k}")


@pytest.fixture
def api(cfg):
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as c:
        yield c


def err(r) -> str:
    return r.json()["error"]["code"]


def new_run(api, **body) -> dict:
    r = api.post("/api/video/runs", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def patch(api, run_id: int, **body) -> dict:
    r = api.patch(f"/api/video/runs/{run_id}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── catalogue ───────────────────────────────────────────────────────────────


def test_models_and_camera_moves(api):
    out = api.get("/api/video/models").json()
    apis = {m["api"] for m in out["models"]}
    assert {"veo", "omni"} <= apis
    assert out["extension_models"] and all(m["extends"] for m in out["extension_models"])
    omni = next(m for m in out["models"] if m["api"] == "omni")
    assert omni["input_video"]["max_seconds"] > 0 and omni["last_frame"] is False and omni["sound_switch"] is False
    moves = api.get("/api/video/camera-moves").json()
    assert moves["categories"] == ["basic", "advanced", "framing"]
    assert len(moves["moves"]) == 60 and {"code", "category"} == set(moves["moves"][0])
    assert all("clip_phrase" not in m for m in moves["moves"])        # words for the model stay on the server


# ── runs and the form ───────────────────────────────────────────────────────


def test_new_run_gets_the_default_model_and_fitting_settings(api):
    run = new_run(api)
    m = catalog.model(None)
    assert run["model_id"] == m["id"] and run["stage"] == "draft" and run["sound"] is True
    assert run["duration"] in catalog.durations(m, run["resolution"])
    assert run["aspect"] in catalog.aspects(m)
    assert run["link"] == f"/chat?video={run['id']}"
    assert run["take"]["ready"] is False and run["take"]["refusal"] == "video_brief_empty"
    assert api.get("/api/video/runs").json()["items"][0]["id"] == run["id"]


def test_animate_a_picture(api):
    pic = stored_png()
    run = new_run(api, first_frame_id=pic["id"], brief="The waves roll in")
    assert run["first_frame"]["id"] == pic["id"] and run["take"]["ready"] is True
    assert run["take"]["prompt"] == "The waves roll in"


def test_switching_models_snaps_the_settings(api):
    veo, omni = video_model("veo"), video_model("omni")
    run = new_run(api, model_id=veo["id"])
    out = patch(api, run["id"], model_id=omni["id"], duration=13)
    assert out["model_id"] == omni["id"] and out["duration"] == max(catalog.durations(omni, out["resolution"]))
    out = patch(api, run["id"], model_id=veo["id"], duration=5, resolution="8k", aspect="1:1")
    assert out["duration"] in (4, 6) and out["resolution"] in catalog.resolutions(veo)
    assert out["aspect"] in catalog.aspects(veo)


@pytest.mark.parametrize("body,code", [
    ({"color": "red"}, "video_field_unknown"),
    ({"camera_move": "barrel_roll_9000"}, "video_camera_unknown"),
    ({"brief": "x" * 20_001}, "video_text_too_long"),
])
def test_bad_values_are_refused(api, body, code):
    run = new_run(api)
    r = api.patch(f"/api/video/runs/{run['id']}", json=body)
    assert r.status_code == 400 and err(r) == code


def test_frames_must_be_pictures(api):
    clip = files.save_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32, mime="video/mp4", name="v.mp4",
                            origin="upload")
    run = new_run(api)
    r = api.patch(f"/api/video/runs/{run['id']}", json={"first_frame_id": clip["id"]})
    assert r.status_code == 400 and err(r) == "video_frame_not_image"
    r = api.post("/api/video/runs", json={"references": [clip["id"]]})
    assert r.status_code == 400 and err(r) == "video_frame_not_image"
    assert db.fetch_value("SELECT COUNT(*) FROM video_runs") == 1      # the refused new run is not left behind


def test_refusals_come_before_money(api):
    omni = video_model("omni")
    veo = video_model("veo")
    first, last = stored_png(), stored_png((0, 0, 0))
    run = new_run(api, model_id=omni["id"], brief="Waves", first_frame_id=first["id"], last_frame_id=last["id"])
    assert run["take"]["refusal"] == "video_last_frame_unsupported"
    run = patch(api, run["id"], model_id=veo["id"], first_frame_id=None)
    assert run["take"]["refusal"] == "video_last_frame_needs_first"
    run = patch(api, run["id"], brief="  ", first_frame_id=first["id"])
    assert run["take"]["refusal"] == "video_brief_empty"
    r = api.post(f"/api/video/runs/{run['id']}/start")
    assert r.status_code == 400 and err(r) == "video_brief_empty"
    assert r.json()["error"]["message"] == "Describe the video first — the text is what gets filmed"
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls") == 0
    assert db.fetch_value("SELECT COUNT(*) FROM jobs") == 0


def test_too_many_references_for_the_model(api):
    lite = next((m for m in catalog.video_models() if m["api"] == "veo" and catalog.max_references(m) == 0), None)
    if lite is None:
        pytest.skip("no video model without references")
    pics = [stored_png((i * 40, 0, 0)) for i in range(2)]
    run = new_run(api, model_id=lite["id"], brief="A shop", references=[p["id"] for p in pics])
    assert run["take"]["refusal"] == "video_too_many_references"
    assert run["take"]["refusal_details"]["max"] == 0


def test_an_opening_frame_shadows_the_references(api):
    veo = video_model("veo", refs=True)
    ref, first = stored_png(), stored_png((255, 255, 0))
    run = new_run(api, model_id=veo["id"], brief="A shop", references=[ref["id"]])
    assert run["take"]["references_sent"] == 1 and run["take"]["warnings"] == []
    run = patch(api, run["id"], first_frame_id=first["id"])
    assert run["take"]["ready"] is True and run["take"]["references_sent"] == 0
    assert run["take"]["warnings"] == ["frame_shadows_references"]


def test_preview_has_the_brief_word_for_word_and_the_price(api):
    veo = video_model("veo")
    run = new_run(api, model_id=veo["id"], brief="  A red kite over the sea.\nIt dives.  ", camera_move="zoom_in",
                  duration=6)
    take = run["take"]
    assert take["prompt"].startswith("A red kite over the sea.\nIt dives.\n\nA slow zoom in, ")
    assert take["estimate_usd"] > 0 and take["seconds"] == 6
    omni = video_model("omni")
    run = patch(api, run["id"], model_id=omni["id"], sound=False)
    assert run["take"]["sound"] is True                                 # Omni always has sound


def test_start_queues_one_take_and_archives_the_previous(api):
    run = new_run(api, brief="A boat", title="Harbour")
    r = api.post(f"/api/video/runs/{run['id']}/start")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["busy"] is True and out["status"] == "running" and out["stage"] == "take"
    (clip,) = out["clips"]
    assert clip["kind"] == "take" and clip["status"] == "queued" and clip["prompt"] == "A boat"
    job = db.get("jobs", out["job_id"])
    assert job["kind"] == video.JOB_TAKE and job["title"] == "Harbour" and job["serial_key"] == f"video:{run['id']}"

    r = api.post(f"/api/video/runs/{run['id']}/start")
    assert r.status_code == 409 and err(r) == "video_busy"
    r = api.delete(f"/api/video/runs/{run['id']}")
    assert r.status_code == 409 and err(r) == "video_busy"
    out = api.post(f"/api/video/runs/{run['id']}/stop").json()
    assert out["busy"] is False and out["status"] == "idle" and out["clips"][0]["status"] == "cancelled"

    out = api.post(f"/api/video/runs/{run['id']}/start").json()
    assert [c["number"] for c in out["clips"]] == [2]                    # the first take is archived
    assert db.fetch_value("SELECT COUNT(*) FROM video_clips WHERE archived = 1") == 1
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls") == 0


def test_versions_and_undo_without_a_video(api):
    run = new_run(api, brief="x")
    r = api.post(f"/api/video/runs/{run['id']}/undo")
    assert r.status_code == 409 and err(r) == "video_nothing_to_undo"
    r = api.post(f"/api/video/runs/{run['id']}/versions/1/choose")
    assert r.status_code == 404
    r = api.post(f"/api/video/runs/{run['id']}/frame", json={"at": "last"})
    assert r.status_code == 409 and err(r) == "video_extend_no_video"
    info = api.get(f"/api/video/runs/{run['id']}/extend").json()
    assert info["available"] is False and info["reason"] == "video_extend_no_video"
    r = api.post(f"/api/video/runs/{run['id']}/extend", json={"steps": [{"text": "more", "seconds": 4}]})
    assert r.status_code == 409 and err(r) == "video_extend_no_video"


def test_delete_run_and_media_usages(api):
    pic, ref = stored_png(), stored_png((1, 2, 3))
    run = new_run(api, brief="A cat", first_frame_id=pic["id"], references=[ref["id"]], title="Cat")
    usages = files.usages(pic["id"])
    assert {"type": "video", "id": run["id"], "title": "Cat"} in usages
    assert any(u["type"] == "video" for u in files.usages(ref["id"]))
    assert api.delete(f"/api/video/runs/{run['id']}").json() == {"ok": True}
    assert not any(u["type"] == "video" for u in files.usages(pic["id"]))
    assert api.get(f"/api/video/runs/{run['id']}").status_code == 404


def test_journal_links_point_to_the_chat(api):
    from vf.modules.spend import refs as spend_refs

    pic = stored_png()
    run = new_run(api, brief="A cat", first_frame_id=pic["id"])
    clip_id = runs.add_clip(run["id"], kind="take", model_id=run["model_id"], prompt="A cat", seconds=4)
    found = spend_refs.resolve("video_run", run["id"])
    assert found["link"] == f"/chat?video={run['id']}" and found["title"] == "A cat" and found["thumb_url"]
    clip = spend_refs.resolve("video_clip", clip_id)
    assert clip["title"] == "A cat · 1" and clip["link"] == f"/chat?video={run['id']}"


def test_video_settings_are_defined(database):
    from vf.core import settings

    assert settings.get("video.extend_tail_seconds") == 10
    assert settings.get("video.extend_align") is True
    assert settings.get("video.extend_crossfade_seconds") == pytest.approx(0.2)
    assert settings.get("video.research_cache_days") == 14


def test_web_locales_name_every_camera_move_and_setting(database):
    """The web picker and the settings screen read these names from web/i18n."""
    import json
    from pathlib import Path

    from vf.core import settings

    web = Path(__file__).resolve().parents[2] / "web" / "i18n" / "locales"
    if not web.is_dir():
        pytest.skip("web/ is not mounted")
    keys = [k for d in settings.definitions().values() if d.group == "video"
            for k in (d.meta.get("label_key"), d.meta.get("help_key"))]
    assert len(keys) == 8 and all(keys)
    for lang in ("en", "ru", "uk"):
        texts = json.loads((web / lang / "video.json").read_text(encoding="utf-8"))["video"]
        assert set(texts["cameraMove"]["moves"]) == {m["code"] for m in catalog.camera_moves()}, lang
        assert set(texts["cameraMove"]["groups"]) == set(catalog.camera_categories()), lang
        for key in keys:
            node = texts
            for part in key.split(".")[1:]:
                node = node[part]
            assert node, (lang, key)


def test_omni_check_request_is_the_cheapest(database):
    from vf.modules.video import checks

    omni = video_model("omni")
    req = checks.check_request(omni)
    assert req["seconds"] == min(catalog.durations(omni, req["resolution"]))
    assert req["resolution"] == min(catalog.resolutions(omni), key=catalog.resolution_rank)
    assert models_registry.get(omni["id"])["api"] == "omni"
