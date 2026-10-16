"""Module 04 (image studio): works, frames, settings, blocks, sources, export, price, links."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, models_registry, prompts
from vf.core.errors import AppError
from vf.modules import library
from vf.modules.brand import kits, subjects
from vf.modules.library.templates import check_layers, layer_variables
from vf.modules.spend import refs as spend_refs
from vf.modules.studio import blocks


def png(color=(20, 120, 200), size=(64, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def stored_png(color=(20, 120, 200)) -> dict:
    return files.save_bytes(png(color), mime="image/png", name="pic.png", origin="upload")


def model_making(size: str) -> dict:
    """An enabled image model that makes pictures of this size (ids live only in the seed)."""
    for m in models_registry.list_models("image", enabled_only=True):
        if size in ((m.get("caps") or {}).get("allowed_resolutions") or []):
            return m
    pytest.skip(f"no image model makes {size}")


@pytest.fixture
def api(cfg):
    from vf.main import create_app

    # No job runner: started frames stay queued, nothing is drawn.
    with TestClient(create_app(cfg, run_background=False)) as c:
        yield c


def err(r) -> str:
    return r.json()["error"]["code"]


def new_work(api, **body) -> dict:
    r = api.post("/api/studio/works", json={"title": "Sale", "aspect": "4:5", "frame_count": 2, **body})
    assert r.status_code == 200, r.text
    return r.json()


def block_of(frame: dict, code: str) -> dict:
    return next(b for b in frame["blocks"] if b["code"] == code)


# ── works ───────────────────────────────────────────────────────────────────


def test_create_work_with_defaults(api):
    work = new_work(api, frame_count=3)
    assert work["status"] == "draft" and work["aspect"] == "4:5" and work["image_size"] == "1K"
    assert [f["position"] for f in work["frames"]] == [0, 1, 2]
    assert work["settings"]["text_mode"] == "none" and work["settings"]["series"] is False
    assert work["pilot"] == {"frame_id": None, "accepted": False, "ready": False}
    assert work["cost_usd"] == 0

    frame = work["frames"][0]
    assert frame["status"] == "empty" and frame["waiting"] is False and frame["versions"] == []
    default = models_registry.default_for("image")
    assert frame["effective"]["model_id"] == default["id"]
    assert frame["effective"]["model_title"] == default["title"]
    assert [b["code"] for b in frame["blocks"]] == list(blocks.CODES)
    assert block_of(frame, "output_size")["applies"] is True          # 4:5 has a configured size
    assert block_of(frame, "brand_colors")["reason"] == "no_brand"
    assert block_of(frame, "slide_position")["applies"] is True        # 3 frames, words not drawn


@pytest.mark.parametrize(("body", "status", "code"), [
    ({"aspect": "7:3"}, 400, "bad_aspect"),
    ({"image_size": "8K"}, 400, "bad_size"),
    ({"frame_count": 0}, 400, "too_many_frames"),
    ({"frame_count": 11}, 400, "too_many_frames"),
    ({"frame_count": "many"}, 400, "too_many_frames"),
    ({"settings": {"text_mode": "loud"}}, 400, "bad_text_mode"),
    ({"settings": {"references": [999999]}}, 400, "bad_file"),
    ({"settings": {"photo_style": 999999}}, 400, "bad_style"),
    ({"model_id": "no-such-model"}, 404, "model_unknown"),
])
def test_create_work_rejects_bad_values(api, body, status, code):
    r = api.post("/api/studio/works", json={"frame_count": 1, **body})
    assert r.status_code == status, r.text
    assert err(r) == code


def test_too_many_pictures(api):
    ids = [stored_png((i, i, i))["id"] for i in range(15)]
    r = api.post("/api/studio/works", json={"settings": {"references": ids}})
    assert r.status_code == 400 and err(r) == "too_many_pictures"
    r = api.post("/api/studio/works", json={"settings": {"references": ids[:14]}})
    assert r.status_code == 200 and len(r.json()["settings"]["references"]) == 14


def test_update_work_settings(api):
    work = new_work(api)
    r = api.patch(f"/api/studio/works/{work['id']}", json={
        "title": "  Spring   sale ",
        "settings": {"blocks": {"quality": False, "language": False, "bogus": True},
                     "ideas_brief": "Fresh bread on a table", "pilot_accepted": True, "whatever": 1},
    })
    assert r.status_code == 200, r.text
    work = r.json()
    assert work["title"] == "Spring sale"
    assert work["settings"]["blocks"] == {"quality": False}          # only changes from the defaults
    assert work["settings"]["pilot_accepted"] is False                # not set from outside
    assert "whatever" not in work["settings"]
    assert block_of(work["frames"][0], "quality")["on"] is False

    # Series on, then off: the pilot is forgotten.
    work = api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"series": True}}).json()
    assert work["pilot"]["frame_id"] == work["frames"][0]["id"] and work["frames"][0]["is_pilot"] is True
    work = api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"series": False}}).json()
    assert work["pilot"]["frame_id"] is None and work["frames"][0]["is_pilot"] is False

    # Frame count up and down.
    work = api.patch(f"/api/studio/works/{work['id']}", json={"frame_count": 4}).json()
    assert len(work["frames"]) == 4 and work["frame_count"] == 4
    work = api.patch(f"/api/studio/works/{work['id']}", json={"frame_count": 1}).json()
    assert len(work["frames"]) == 1


def test_archive_and_list(api):
    ids = {t: new_work(api, title=t)["id"] for t in ("Alpha", "Beta", "Gamma")}
    r = api.post(f"/api/studio/works/{ids['Beta']}/archive")
    assert r.json()["status"] == "archived" and r.json()["archived_at"]

    assert api.get("/api/studio/works").json()["total"] == 2
    archived = api.get("/api/studio/works", params={"status": "archived"}).json()
    assert [w["title"] for w in archived["items"]] == ["Beta"]
    assert api.get("/api/studio/works", params={"status": "all"}).json()["total"] == 3
    found = api.get("/api/studio/works", params={"q": "gam"}).json()
    assert [w["title"] for w in found["items"]] == ["Gamma"]
    item = found["items"][0]
    assert item["done_count"] == 0 and item["cover"] is None and item["cost_usd"] == 0 and item["frame_count"] == 2

    # Back from the archive: a draft without pictures, active with one.
    assert api.post(f"/api/studio/works/{ids['Beta']}/unarchive").json()["status"] == "draft"
    beta = api.get(f"/api/studio/works/{ids['Beta']}").json()
    api.post(f"/api/studio/frames/{beta['frames'][1]['id']}/pick", json={"file_id": stored_png()["id"]})
    assert api.get(f"/api/studio/works/{ids['Beta']}").json()["status"] == "active"
    api.post(f"/api/studio/works/{ids['Beta']}/archive")
    assert api.post(f"/api/studio/works/{ids['Beta']}/unarchive").json()["status"] == "active"
    item = next(w for w in api.get("/api/studio/works").json()["items"] if w["id"] == ids["Beta"])
    assert item["done_count"] == 1 and item["cover"]["id"]


def test_unknown_work_and_frame(api):
    assert api.get("/api/studio/works/999").status_code == 404
    assert api.get("/api/studio/frames/999").status_code == 404


# ── frames ──────────────────────────────────────────────────────────────────


def test_frames_add_reorder_delete(api):
    work = new_work(api)
    first, second = (f["id"] for f in work["frames"])
    r = api.post(f"/api/studio/works/{work['id']}/frames", json={"after": first})
    assert r.status_code == 200, r.text
    added = r.json()
    assert added["position"] == 1
    work = api.get(f"/api/studio/works/{work['id']}").json()
    assert [f["id"] for f in work["frames"]] == [first, added["id"], second] and work["frame_count"] == 3

    order = [second, first, added["id"]]
    work = api.post(f"/api/studio/works/{work['id']}/reorder", json={"ids": order}).json()
    assert [f["id"] for f in work["frames"]] == order
    assert [f["position"] for f in work["frames"]] == [0, 1, 2]
    for bad in ([second, first], [second, first, first], "x"):
        r = api.post(f"/api/studio/works/{work['id']}/reorder", json={"ids": bad})
        assert r.status_code == 400 and err(r) == "bad_order"

    work = api.delete(f"/api/studio/frames/{first}").json()
    assert [f["id"] for f in work["frames"]] == [second, added["id"]] and work["frame_count"] == 2
    api.delete(f"/api/studio/frames/{second}")
    r = api.delete(f"/api/studio/frames/{added['id']}")
    assert r.status_code == 409 and err(r) == "last_frame"


def test_at_most_ten_frames(api):
    work = new_work(api, frame_count=10)
    r = api.post(f"/api/studio/works/{work['id']}/frames")
    assert r.status_code == 400 and err(r) == "too_many_frames"


def test_reorder_resets_the_pilot(api):
    work = new_work(api, settings={"series": True})
    first, second = (f["id"] for f in work["frames"])
    api.post(f"/api/studio/frames/{first}/pick", json={"file_id": stored_png()["id"]})
    out = api.post(f"/api/studio/works/{work['id']}/accept-pilot").json()
    # Accepted even though the other frame cannot go yet (no brief): it is listed, not an error.
    assert out["queued"] == [] and out["skipped"] == [{"frame_id": second, "reason": "brief_required"}]
    work = out["work"]
    assert work["pilot"]["accepted"] is True
    work = api.post(f"/api/studio/works/{work['id']}/reorder", json={"ids": [second, first]}).json()
    assert work["pilot"] == {"frame_id": second, "accepted": False, "ready": False}


def test_update_frame(api):
    work = new_work(api)
    fid = work["frames"][0]["id"]
    ref = stored_png()["id"]
    big = model_making("2K")
    r = api.patch(f"/api/studio/frames/{fid}", json={
        "brief": "  A loaf of bread  ",
        "overrides": {"model_id": big["id"], "image_size": "2K", "references": [ref], "bogus": 1, "feedback": ""},
        "text_blocks": [{"role": "headline", "text": "Fresh"}, {"role": "weird", "text": "Every day"},
                        "plain words", {"text": "   "}],
    })
    assert r.status_code == 200, r.text
    frame = r.json()
    assert frame["brief"] == "A loaf of bread"
    assert frame["overrides"] == {"model_id": big["id"], "image_size": "2K", "references": [ref]}
    assert [b["role"] for b in frame["text_blocks"]] == ["headline", "body", "body"]
    eff = frame["effective"]
    assert eff["model_id"] == big["id"] and eff["image_size"] == "2K" and eff["references"] == [ref]
    assert block_of(frame, "output_size")["reason"] == "large_size"    # 2K keeps the model's own size
    assert block_of(frame, "project_references")["applies"] is True

    # References [] means "none" for this frame, even when the work has some.
    api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"references": [ref]}})
    frame = api.patch(f"/api/studio/frames/{fid}", json={"overrides": {"references": []}}).json()
    assert frame["effective"]["references"] == []
    assert block_of(frame, "project_references")["reason"] == "no_references"

    r = api.patch(f"/api/studio/frames/{fid}", json={"text_blocks": [{"text": f"w{i}"} for i in range(7)]})
    assert r.status_code == 400 and err(r) == "too_many_text_blocks"
    r = api.patch(f"/api/studio/frames/{fid}", json={"overrides": {"image_size": "9K"}})
    assert r.status_code == 400 and err(r) == "bad_size"


def test_size_is_what_the_model_makes(api):
    small = next((m for m in models_registry.list_models("image", enabled_only=True)
                  if (m.get("caps") or {}).get("allowed_resolutions") == ["1K"]), None)
    if small is None:
        pytest.skip("no 1K-only image model")
    work = new_work(api, model_id=small["id"], image_size="4K")
    eff = work["frames"][0]["effective"]
    assert eff["image_size"] == "1K" and eff["size_wanted"] == "4K"


def test_photo_and_image_style(api):
    photo = library.create_style({"title": "Film", "prompt": "Shot on 35mm film", "kind": "photo_style"})
    work = new_work(api, settings={"photo_style": photo["id"], "style": "Soft pastel watercolour"})
    frame = work["frames"][0]
    assert block_of(frame, "photo_style")["applies"] is True
    assert block_of(frame, "image_style")["applies"] is True
    work = api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"photo_style": None, "style": ""}}).json()
    assert block_of(work["frames"][0], "photo_style")["reason"] == "no_photo_style"
    assert block_of(work["frames"][0], "image_style")["reason"] == "no_style"


# ── brand kit ───────────────────────────────────────────────────────────────


def test_kit_snapshot_feeds_the_blocks(api):
    kit = kits.create_kit("Bakery", colors=["#aa5500"], tone="Warm and friendly")
    ref = kits.add_image_asset(kit["id"], "reference", png(), filename="ref.png")
    work = new_work(api, kit_id=kit["id"])
    assert work["brand"]["name"] == "Bakery" and work["kit_changed"] is False
    frame = work["frames"][0]
    assert block_of(frame, "brand_colors")["applies"] is True
    assert block_of(frame, "tone_of_voice")["applies"] is True
    assert block_of(frame, "logo")["reason"] == "no_logo"
    assert block_of(frame, "brand_fonts")["reason"] == "no_fonts"
    assert block_of(frame, "identity_assets")["reason"] == "no_elements"
    assert frame["effective"]["references"] == [ref["file_id"]]       # kit references join in

    work = api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"kit_references": False}}).json()
    assert work["frames"][0]["effective"]["references"] == []

    kits.add_image_asset(kit["id"], "logo", png((0, 0, 0)), filename="logo.png")
    work = api.get(f"/api/studio/works/{work['id']}").json()
    assert work["kit_changed"] is True
    assert block_of(work["frames"][0], "logo")["reason"] == "no_logo"   # the copy is not changed by itself
    work = api.post(f"/api/studio/works/{work['id']}/refresh-brand").json()
    assert work["kit_changed"] is False
    assert block_of(work["frames"][0], "logo")["applies"] is True

    plain = new_work(api)
    r = api.post(f"/api/studio/works/{plain['id']}/refresh-brand")
    assert r.status_code == 409 and err(r) == "no_kit"


# ── pictures from elsewhere, versions, export ───────────────────────────────


def test_pick_upload_restore_and_export(api):
    work = new_work(api, title="Bread & Butter")
    first, second = (f["id"] for f in work["frames"])
    r = api.get(f"/api/studio/works/{work['id']}/export")
    assert r.status_code == 409 and err(r) == "nothing_to_export"

    a, b = stored_png((255, 0, 0)), stored_png((0, 255, 0))
    frame = api.post(f"/api/studio/frames/{second}/pick",
                     json={"file_id": a["id"], "source": "avatar", "source_ref": {"avatar_id": 3, "x": [1]}}).json()
    assert frame["status"] == "done" and frame["source"] == "avatar" and frame["source_ref"] == {"avatar_id": 3}
    frame = api.post(f"/api/studio/frames/{second}/pick", json={"file_id": b["id"]}).json()
    assert frame["file_id"] == b["id"] and frame["source"] == "library"
    assert [v["current"] for v in frame["versions"]] == [False, True]
    assert {v["mode"] for v in frame["versions"]} == {"source"}

    for body, code in (({"file_id": a["id"], "source": "generated"}, "bad_request"),
                       ({"file_id": 999999}, "bad_file")):
        r = api.post(f"/api/studio/frames/{second}/pick", json=body)
        assert r.status_code == 400 and err(r) == code

    # Upload straight into the other frame.
    r = api.post(f"/api/studio/frames/{first}/source", files={"file": ("up.png", png((0, 0, 255)), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "upload"
    for data, code in ((b"", "empty_file"), (b"not a picture at all", "bad_image_type")):
        r = api.post(f"/api/studio/frames/{first}/source", files={"file": ("x.png", data, "image/png")})
        assert r.status_code == 400 and err(r) == code

    # Going back is free; a version whose picture was deleted cannot come back.
    frame = api.post(f"/api/studio/frames/{second}/versions/0/restore").json()
    assert frame["file_id"] == a["id"] and frame["source"] == "avatar"
    r = api.post(f"/api/studio/frames/{second}/versions/5/restore")
    assert r.status_code == 404 and err(r) == "version_unknown"
    api.post(f"/api/studio/frames/{second}/versions/1/restore")
    files.delete(a["id"])                       # an old version does not hold the picture
    r = api.post(f"/api/studio/frames/{second}/versions/0/restore")
    assert r.status_code == 404 and err(r) == "version_unknown"

    r = api.get(f"/api/studio/works/{work['id']}/export")
    assert r.status_code == 200
    assert 'filename="bread-butter-' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["01.png", "02.png"]
        assert zf.read("02.png") == files.read_bytes(b["id"])


def test_media_usages_and_journal_links(api):
    shown, ref, attached = stored_png((1, 1, 1)), stored_png((2, 2, 2)), stored_png((3, 3, 3))
    work = new_work(api, settings={"references": [ref["id"]]})
    fid = work["frames"][0]["id"]
    api.post(f"/api/studio/frames/{fid}/pick", json={"file_id": shown["id"]})
    api.patch(f"/api/studio/frames/{fid}", json={"overrides": {"attachments": [attached["id"]]}})
    for row in (shown, ref, attached):
        with pytest.raises(AppError) as e:
            files.delete(row["id"])
        assert e.value.code == "file_in_use"
        assert {"type": "studio", "id": work["id"], "title": "Sale"} in e.value.details["usages"]

    found = spend_refs.resolve("work", work["id"])
    assert found["exists"] is True and found["title"] == "Sale" and found["link"] == f"/chat?work={work['id']}"
    assert found["thumb_url"]
    found = spend_refs.resolve("frame", fid)
    assert found["title"] == "Sale · 1" and found["link"] == f"/chat?frame={fid}" and found["url"]

    # Deleting the work keeps the pictures in the media library.
    assert api.delete(f"/api/studio/works/{work['id']}").json() == {"ok": True}
    assert api.get(f"/api/studio/works/{work['id']}").status_code == 404
    assert spend_refs.resolve("work", work["id"])["exists"] is False
    assert db.get("files", shown["id"]) is not None
    files.delete(shown["id"])


# ── starting and stopping (no runner: frames stay queued) ───────────────────


def test_start_needs_a_brief_and_cancel_drops_the_queued_job(api):
    work = new_work(api)
    fid = work["frames"][0]["id"]
    r = api.post(f"/api/studio/frames/{fid}/generate")
    assert r.status_code == 400 and err(r) == "brief_required"
    r = api.post(f"/api/studio/works/{work['id']}/generate")
    assert r.status_code == 400 and err(r) == "brief_required"

    api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"ideas_brief": "Bread on a table"}})
    r = api.post(f"/api/studio/frames/{fid}/generate")
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert r.json()["frame"]["status"] == "queued"
    r = api.post(f"/api/studio/frames/{fid}/generate")
    assert r.status_code == 409 and err(r) == "frame_busy"
    r = api.delete(f"/api/studio/works/{work['id']}")
    assert r.status_code == 409 and err(r) == "frame_busy"

    frame = api.post(f"/api/studio/frames/{fid}/cancel").json()
    assert frame["status"] == "empty"
    assert db.get("jobs", job_id)["status"] == "cancelled"

    out = api.post(f"/api/studio/works/{work['id']}/generate").json()
    assert sorted(out["queued"]) == sorted(f["id"] for f in work["frames"]) and out["skipped"] == []


def test_edit_needs_a_picture_and_words(api):
    work = new_work(api)
    fid = work["frames"][0]["id"]
    r = api.post(f"/api/studio/frames/{fid}/edit", json={"edit": "make it red"})
    assert r.status_code == 409 and err(r) == "frame_no_picture"
    api.post(f"/api/studio/frames/{fid}/pick", json={"file_id": stored_png()["id"]})
    r = api.post(f"/api/studio/frames/{fid}/edit", json={"edit": "  "})
    assert r.status_code == 400 and err(r) == "edit_text_required"
    r = api.post(f"/api/studio/frames/{fid}/edit", json={"edit": "red", "region": {"box": {"x": 0, "y": 0}}})
    assert r.status_code == 400 and err(r) == "bad_request"
    r = api.post(f"/api/studio/frames/{fid}/edit",
                 json={"edit": "make it red", "region": {"label": "cup", "box": {"x": .1, "y": .1, "w": .2, "h": .2}}})
    assert r.status_code == 200 and r.json()["frame"]["status"] == "queued"


def test_series_draws_the_pilot_first(api):
    work = new_work(api, frame_count=3, settings={"series": True, "ideas_brief": "Bread"})
    pilot, *rest = (f["id"] for f in work["frames"])
    r = api.post(f"/api/studio/works/{work['id']}/accept-pilot")
    assert r.status_code == 409 and err(r) == "pilot_not_ready"
    out = api.post(f"/api/studio/works/{work['id']}/generate").json()
    assert out["queued"] == [pilot]
    assert out["skipped"] == [{"frame_id": f, "reason": "pilot_not_ready"} for f in rest]


# ── price before the button ─────────────────────────────────────────────────


def test_estimate(api):
    est = api.post("/api/studio/estimate", json={"action": "new", "count": 3, "input_images": 2}).json()
    assert est["count"] == 3 and est["usd"] > 0 and est["image_size"] == "1K"
    one = api.post("/api/studio/estimate", json={"action": "new", "count": 1}).json()
    assert est["usd"] >= one["usd"] * 3 - 1e-9

    work = new_work(api, frame_count=3)
    fid = work["frames"][0]["id"]
    est = api.post("/api/studio/estimate", json={"action": "frame", "frame_id": fid}).json()
    assert est["usd"] == 0 and est["count"] == 0 and est["items"][0]["error"] == "brief_required"

    api.patch(f"/api/studio/works/{work['id']}", json={"settings": {"ideas_brief": "Bread",
                                                                     "references": [stored_png()["id"]]}})
    est = api.post("/api/studio/estimate", json={"action": "frame", "frame_id": fid}).json()
    assert est["usd"] > 0 and est["items"][0]["input_images"] == 1
    every = api.post("/api/studio/estimate", json={"action": "generate_all", "work_id": work["id"]}).json()
    assert every["count"] == 3 and every["usd"] == pytest.approx(est["usd"] * 3, abs=1e-3)

    edit = api.post("/api/studio/estimate", json={"action": "edit", "frame_id": fid, "region": {"id": "x"}}).json()
    assert edit["items"][0]["input_images"] == 2 and edit["usd"] > 0
    find = api.post("/api/studio/estimate", json={"action": "find_objects", "frame_id": fid}).json()
    assert find["items"][0]["cached"] is False

    r = api.post("/api/studio/estimate", json={"action": "fly"})
    assert r.status_code == 400 and err(r) == "bad_request"


def test_estimate_after_the_pilot(api):
    work = new_work(api, frame_count=3, settings={"series": True, "ideas_brief": "Bread"})
    est = api.post("/api/studio/estimate", json={"action": "generate_all", "work_id": work["id"]}).json()
    assert est["count"] == 1                                    # only the pilot until it is accepted
    api.post(f"/api/studio/frames/{work['frames'][0]['id']}/pick", json={"file_id": stored_png()["id"]})
    est = api.post("/api/studio/estimate", json={"action": "accept_pilot", "work_id": work["id"]}).json()
    assert est["count"] == 2
    assert all(i["input_images"] == 1 for i in est["items"])    # the pilot's picture goes with each


# ── prompt files and blocks ─────────────────────────────────────────────────


def test_prompt_files_are_sound(database):
    assert prompts.check_all() == []
    assert check_layers() == []
    for code in ("STUDIO_FRAME", "STUDIO_FIND_OBJECTS"):
        assert prompts.get(code).version >= 1
    # The captions the studio puts before pictures: every one exists and fills all its values.
    from vf.modules.studio import compose

    values = {"count": 2, "index": 1, "name": "Loaf", "kind": "product", "description": "Rye", "angle": "front"}
    for code in sorted(c for c in prompts.load() if c.startswith("STUDIO_PART_")):
        text = compose._part(code, **{k: v for k, v in values.items() if k in prompts.get(code).variables})
        assert text and "{{" not in text, code
    assert compose._part("STUDIO_PART_SUBJECT_PHOTO_ANGLE", name="Loaf", index=1, count=2,
                         angle="front") == "Loaf — photo 1/2, angle: front"


def full_facts() -> blocks.Facts:
    brand = {
        "name": "Bakery", "tone": "Warm", "colors": [{"hex": "#AA5500", "label": "crust"}, {"hex": "#FFFFFF"}],
        "fonts": [{"category": "serif"}, {"category": "serif"}, {"category": "mono"}],
        "logos": [{"file_id": 1, "name": "logo"}], "elements": [{"kind": "frame", "file_id": 2, "name": "Ribbon"}],
    }
    return blocks.Facts(
        text_mode="model", words=[{"role": "headline", "text": "Fresh"}, {"role": "body", "text": "Daily"}],
        brand=brand, references=2, attachments=1,
        subjects=[{"name": "Loaf", "kind": "product", "description": "Round  rye loaf"}],
        style="Watercolour", photo_style="35mm film", position=2, frame_count=4, size=(1080, 1350),
        variant=3, feedback="Less blue", language="uk",
    )


def test_every_block_gets_all_its_values(database):
    f = full_facts()
    for code in blocks.CODES:
        wanted = set(layer_variables(blocks.layer_code(code))["values"])
        assert wanted <= set(blocks._values(code, f)), code
    texts = blocks.render(list(blocks.CODES), f)
    assert len(texts) == len(blocks.CODES)
    joined = "\n".join(texts)
    assert "{{" not in joined
    for piece in ("1080", "#AA5500 (crust)", "Warm", "Loaf [product]: Round rye loaf", "Watercolour",
                  "35mm film", "[headline]\nFresh", "Less blue", "Ukrainian", "frame: Ribbon"):
        assert piece in joined, piece


def reasons(f: blocks.Facts) -> dict:
    return {b["code"]: b["reason"] for b in blocks.catalog({}, f)}


def test_block_reasons():
    empty = reasons(blocks.Facts())
    assert empty == {
        "output_size": "no_size", "language": "text_not_drawn", "brand_colors": "no_brand",
        "brand_fonts": "no_brand", "tone_of_voice": "no_brand", "logo": "no_brand",
        "project_references": "no_references", "task_attachments": "no_attachments", "subjects": "no_subjects",
        "identity_assets": "no_brand", "image_style": "no_style", "photo_style": "no_photo_style",
        "slide_position": "single_frame", "slide_text": "no_overlay", "draw_text": "text_not_drawn",
        "no_lettering": None, "quality": None, "variant_diversity": "first_version", "feedback": "no_feedback",
    }
    bare_brand = reasons(blocks.Facts(brand={"name": "x"}, large=True, text_mode="overlay", frame_count=3))
    assert bare_brand["output_size"] == "large_size"
    assert bare_brand["brand_colors"] == "no_colors" and bare_brand["brand_fonts"] == "no_fonts"
    assert bare_brand["tone_of_voice"] == "no_tone" and bare_brand["logo"] == "no_logo"
    assert bare_brand["identity_assets"] == "no_elements" and bare_brand["slide_text"] == "no_words"
    assert bare_brand["slide_position"] is None

    full = reasons(full_facts())
    assert full["slide_position"] == "text_drawn" and full["no_lettering"] == "text_drawn"
    assert all(full[c] is None for c in blocks.CODES if c not in ("slide_position", "no_lettering", "slide_text"))

    # Off by default, or turned off: not sent even when it applies.
    on = blocks.active({"quality": False}, full_facts())
    assert "quality" not in on and "language" not in on and "draw_text" in on
    assert blocks.active({"language": True}, full_facts())[1] == "language"


def test_subjects_feed_the_block(api):
    loaf = subjects.create_subject("Loaf", kind="product", description="Round rye loaf")
    subjects.add_photo_upload(loaf["id"], png(), filename="loaf.png")
    work = new_work(api, settings={"subjects": [loaf["id"]]})
    assert block_of(work["frames"][0], "subjects")["applies"] is True
