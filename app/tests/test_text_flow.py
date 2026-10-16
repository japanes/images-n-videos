"""Module 06 (text on image), stub mode: open a frame picture, place the words (without the
paid vision call too), save as a new frame version that reopens with its layers, the paid text
steps with their journal refs, ready layouts, new backgrounds, prices, links from the media
library and the spend screen, and the HTTP routes."""

import asyncio
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, jobs, settings
from vf.core.errors import AppError
from vf.core.google.limiter import limiter
from vf.modules import chat, studio, text
from vf.modules.chat import messages
from vf.modules.spend import refs as spend_refs
from vf.modules.text import backgrounds, designs, estimate, layouts, texts


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
    jobs.runner.paused = None


@pytest.fixture
def api(cfg):
    from vf.main import create_app

    with TestClient(create_app(cfg, run_background=False)) as c:
        yield c


def err(r) -> str:
    return r.json()["error"]["code"]


def stored_png(color=(20, 120, 200), size=(400, 500)) -> dict:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return files.save_bytes(buf.getvalue(), mime="image/png", name="pic.png", origin="upload")


def calls(purpose: str) -> list[dict]:
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def refs_of(call_id: int) -> set[tuple[str, int]]:
    rows = db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))
    return {(r["ref_type"], r["ref_id"]) for r in rows}


def code_of(exc_info) -> str:
    return exc_info.value.code


def make_frame(words=(("headline", "Fresh coffee"), ("body", "Every morning from seven"))) -> dict:
    picture = stored_png()
    work = studio.create_work({"title": "Cafe", "aspect": "4:5", "frame_count": 2})
    frame_id = work["frames"][0]["id"]
    studio.pick_picture(frame_id, picture["id"])
    if words:
        studio.update_frame(frame_id, {"text_blocks": [{"role": r, "text": t} for r, t in words]})
    c = chat.create_chat({})
    mid = messages.add_message(c["id"], type="result", kind="image", mode="image", status="done")
    return {"frame_id": frame_id, "file_id": picture["id"], "chat_id": c["id"], "message_id": mid,
            "work_id": work["id"]}


def open_one(setup: dict) -> dict:
    return text.open_design({"frame_id": setup["frame_id"], "chat_id": setup["chat_id"],
                             "message_id": setup["message_id"]})


def design_refs(design: dict, setup: dict) -> set[tuple[str, int]]:
    return {("text_design", design["id"]), ("frame", setup["frame_id"]), ("chat", setup["chat_id"]),
            ("chat_message", setup["message_id"])}


# ── opening ─────────────────────────────────────────────────────────────────


def test_open_takes_the_frame_words_and_reuses_the_draft():
    setup = make_frame()
    d = open_one(setup)
    assert d["frame_id"] == setup["frame_id"] and d["background"]["file_id"] == setup["file_id"]
    assert [(t["role"], t["text"]) for t in d["texts"]] == [("headline", "Fresh coffee"),
                                                            ("body", "Every morning from seven")]
    assert d["layers"] == [] and d["status"] == "draft"
    assert (d["chat_id"], d["message_id"]) == (setup["chat_id"], setup["message_id"])
    assert d["fallback_font"] == "Roboto" and d["frame"]["count"] == 2
    again = text.open_design({"frame_id": setup["frame_id"], "chat_id": 9999, "message_id": 9999})
    assert again["id"] == d["id"] and again["chat_id"] == setup["chat_id"]


def test_open_refuses_what_it_cannot_use():
    with pytest.raises(AppError) as e:
        text.open_design({})
    assert code_of(e) == "bad_request"
    work = studio.create_work({"title": "Empty", "aspect": "1:1", "frame_count": 1})
    with pytest.raises(AppError) as e:
        text.open_design({"frame_id": work["frames"][0]["id"]})
    assert code_of(e) == "no_picture"
    setup = make_frame()
    note = files.save_bytes(b"hello", mime="text/plain", name="x.txt", origin="upload")
    with pytest.raises(AppError) as e:
        text.open_design({"frame_id": setup["frame_id"], "file_id": note["id"]})
    assert code_of(e) == "not_an_image"


# ── placing ─────────────────────────────────────────────────────────────────


async def test_place_without_vision_uses_the_bottom_third():
    setup = make_frame()
    d = open_one(setup)
    out = await designs.place(d["id"], {})
    placement, layers = out["placement"], out["design"]["layers"]
    assert set(placement["sources"].values()) == {"fallback"} and placement["error"] is None
    assert placement["cost_usd"] == 0 and placement["vision"] is False
    assert calls("text_placement") == []
    assert [x["text"] for x in layers] == ["Fresh coffee", "Every morning from seven"]
    assert all(x["type"] == "text" and x["y"] >= 0.5 and x["y"] + x["h"] <= 1.0 for x in layers)
    assert layers[0]["y"] < layers[1]["y"]

    # placed words keep their places; changed words follow their layer
    again = await designs.place(d["id"], {})
    assert set(again["placement"]["sources"].values()) == {"layer"}
    assert [x["id"] for x in again["design"]["layers"]] == [x["id"] for x in layers]
    texts_now = [{**t, "text": "Hot tea"} if t["role"] == "headline" else t for t in d["texts"]]
    changed = designs.patch(d["id"], {"texts": texts_now})
    assert changed["layers"][0]["text"] == "Hot tea"
    fresh = await designs.place(d["id"], {"replace": True})
    assert set(fresh["placement"]["sources"].values()) == {"fallback"}

    designs.patch(d["id"], {"texts": []})
    with pytest.raises(AppError) as e:
        await designs.place(d["id"], {})
    assert code_of(e) == "no_text"


async def test_place_follows_the_text_map_of_the_frame():
    setup = make_frame()
    db.update("frames", setup["frame_id"], {"text_zones_json": {"zones": [
        {"id": "z1", "role": "headline", "box": {"x": 10, "y": 5, "width": 80, "height": 12},
         "typography": {"case": "uppercase"}, "alignment": "left"}]}})
    d = open_one(setup)
    out = await designs.place(d["id"], {"vision": True})
    sources = out["placement"]["sources"]
    head, body = d["texts"]
    assert sources[head["id"]] == "zone" and sources[body["id"]] == "vision"
    layer = next(x for x in out["design"]["layers"] if x["block_id"] == head["id"])
    assert (layer["x"], layer["y"], layer["w"], layer["h"]) == (0.1, 0.05, 0.8, 0.12)
    assert layer["uppercase"] is True and layer["align"] == "left"
    # only the line the map had no place for went to the model
    assert len(calls("text_placement")) == 1


async def test_vision_places_the_rest_and_is_journaled():
    setup = make_frame()
    d = open_one(setup)
    preview = await designs.place(d["id"], {"preview": True})
    assert preview["blocks"] == 2 and "Fresh coffee" in preview["text"] and preview["system"]
    assert calls("text_placement") == []

    out = await designs.place(d["id"], {"vision": True})
    assert set(out["placement"]["sources"].values()) == {"vision"}
    assert out["placement"]["cost_usd"] > 0 and out["placement"]["model_id"]
    rows = calls("text_placement")
    assert len(rows) == 1 and rows[0]["status"] == "success" and rows[0]["prompt_code"] == "text.placement"
    assert refs_of(rows[0]["id"]) == design_refs(d, setup)
    assert out["design"]["cost_usd"] > 0
    for layer in out["design"]["layers"]:
        assert 0 <= layer["x"] and layer["x"] + layer["w"] <= 1 and 0 <= layer["y"] and layer["y"] + layer["h"] <= 1

    # every block has a place: nothing would be sent
    assert (await designs.place(d["id"], {"preview": True}))["text"] == ""


async def test_a_failed_vision_call_still_places_the_words():
    setup = make_frame(words=(("headline", "[stub:error=permission_denied] Big sale"),))
    d = open_one(setup)
    out = await designs.place(d["id"], {"vision": True})
    assert out["placement"]["error"]["code"] == "permission_denied"
    assert set(out["placement"]["sources"].values()) == {"fallback"}
    assert len(out["design"]["layers"]) == 1
    rows = calls("text_placement")
    assert rows and rows[-1]["status"] == "error" and rows[-1]["error_code"] == "permission_denied"


# ── saving ──────────────────────────────────────────────────────────────────


async def test_save_makes_a_new_frame_version_and_reopens_with_the_layers():
    setup = make_frame()
    d = open_one(setup)
    placed = (await designs.place(d["id"], {}))["design"]
    shape = {"type": "shape", "id": "band", "fill": "#000000", "opacity": 0.4, "x": 0, "y": 0.6, "w": 1, "h": 0.4}
    edited = designs.patch(d["id"], {"layers": [shape, *placed["layers"]]})
    out = text.save_design(d["id"])
    result_id = out["file"]["id"]
    assert out["design"]["status"] == "saved" and out["design"]["result"]["file_id"] == result_id
    assert out["report"]["width"] == 400 and out["report"]["missing_chars"] == ""

    frame = db.get("frames", setup["frame_id"])
    assert frame["file_id"] == result_id
    assert frame["clean_file_id"] == setup["file_id"]       # the picture without the words
    assert frame["text_layers_json"] == edited["layers"]
    assert frame["versions_json"][-1]["source"] == "editor" and frame["versions_json"][-1]["file_id"] == result_id
    assert frame["source_ref_json"] == {"design_id": d["id"]}
    assert [b["text"] for b in frame["text_blocks_json"]] == ["Fresh coffee", "Every morning from seven"]
    assert db.get("files", result_id)["source_type"] == "text_design"
    saved_png = Image.open(io.BytesIO(files.read_bytes(result_id)))
    assert saved_png.size == (400, 500)

    # reopening the saved picture brings the same layers back (by the picture, or the frame alone)
    again = text.open_design({"frame_id": setup["frame_id"], "file_id": result_id})
    assert again["id"] == d["id"] and again["layers"] == edited["layers"]
    assert again["background"]["file_id"] == setup["file_id"]
    assert text.open_design({"frame_id": setup["frame_id"]})["id"] == d["id"]

    # a second save; the first picture, opened again, gets its own layers back in a new design
    moved = [{**x, "y": 0.1} if x["type"] == "text" else x for x in edited["layers"]]
    designs.patch(d["id"], {"layers": moved})
    second = text.save_design(d["id"])["file"]["id"]
    assert second != result_id and db.get("frames", setup["frame_id"])["file_id"] == second
    older = text.open_design({"frame_id": setup["frame_id"], "file_id": result_id})
    assert older["id"] != d["id"] and older["layers"] == edited["layers"]
    assert older["background"]["file_id"] == setup["file_id"]
    latest = text.open_design({"frame_id": setup["frame_id"], "file_id": second})
    assert latest["id"] == d["id"] and [x["y"] for x in latest["layers"] if x["type"] == "text"] == [0.1, 0.1]
    assert len(db.fetch_all("SELECT id FROM text_saves WHERE frame_id = ?", (setup["frame_id"],))) == 2


def test_save_needs_a_background():
    setup = make_frame()
    d = open_one(setup)
    db.update("text_designs", d["id"], {"background_file_id": None})
    with pytest.raises(AppError) as e:
        text.save_design(d["id"])
    assert code_of(e) == "no_picture"


def test_links_from_the_media_library_and_the_spend_screen():
    setup = make_frame()
    d = open_one(setup)
    used = [u for u in files.usages(setup["file_id"]) if u["type"] == "text"]
    assert [u["id"] for u in used] == [d["id"]]
    assert used[0]["link"] == "/chat/{}?message={}".format(setup["chat_id"], setup["message_id"])
    ref = spend_refs.resolve("text_design", d["id"])
    assert ref["exists"] and ref["title"].startswith("Text on image") and ref["link"] == used[0]["link"]
    logo = stored_png((0, 200, 0), (40, 40))
    designs.patch(d["id"], {"layers": [{"type": "logo", "file_id": logo["id"]}]})
    assert [u["id"] for u in files.usages(logo["id"]) if u["type"] == "text"] == [d["id"]]


# ── the words (paid steps) ──────────────────────────────────────────────────


async def test_write_keeps_locked_lines_and_is_journaled():
    setup = make_frame()
    d = open_one(setup)
    designs.patch(d["id"], {"texts": [{"role": "headline", "text": "Keep me", "locked": True},
                                      {"role": "body", "text": "old words"}]})
    preview = await texts.write(d["id"], {"preview": True, "note": "Autumn menu", "use_brief": True})
    assert "Autumn menu" in preview["text"] and calls("text_write") == []

    out = await texts.write(d["id"], {"note": "Autumn menu"})
    assert out["texts"][0]["text"] == "Keep me" and out["texts"][1]["text"] != "old words"
    assert [t["text"] for t in out["previous"]] == ["Keep me", "old words"]
    assert out["cost_usd"] > 0
    rows = calls("text_write")
    assert len(rows) == 1 and rows[0]["prompt_code"] == "text.write"
    assert refs_of(rows[0]["id"]) == design_refs(d, setup)
    assert text.view(d["id"])["texts"][1]["text"] == out["texts"][1]["text"]

    # nothing yet: the model writes the blocks itself
    designs.patch(d["id"], {"texts": []})
    fresh = await texts.write(d["id"], {})
    assert len(fresh["texts"]) == 2 and all(t["text"] for t in fresh["texts"])


async def test_variants_are_offered_not_put_in():
    setup = make_frame()
    d = open_one(setup)
    with pytest.raises(AppError) as e:
        await texts.variants(d["id"], {})
    assert code_of(e) == "empty_prompt"
    preview = await texts.variants(d["id"], {"note": "a headline about coffee", "count": 3, "use_system": True,
                                             "use_language": True, "preview": True})
    assert preview["count"] == 3 and "a headline about coffee" in preview["text"] and preview["system"]
    assert calls("text_variants") == []

    out = await texts.variants(d["id"], {"note": "a headline about coffee", "count": 2})
    assert len(out["variants"]) == 2 and out["errors"] == [] and out["cost_usd"] > 0
    rows = calls("text_variants")
    assert len(rows) == 2 and all(refs_of(r["id"]) == design_refs(d, setup) for r in rows)
    assert text.view(d["id"])["texts"] == d["texts"]

    with pytest.raises(AppError) as e:
        await texts.variants(d["id"], {"note": "[stub:error=permission_denied] coffee"})
    assert code_of(e) == "permission_denied"
    assert calls("text_variants")[-1]["status"] == "error"


async def test_humanize_is_its_own_button():
    setup = make_frame()
    d = open_one(setup)
    designs.patch(d["id"], {"texts": [{"role": "headline", "text": "Keep me", "locked": True},
                                      {"role": "body", "text": "Leverage our synergy"}]})
    preview = await texts.humanize(d["id"], {"preview": True})
    assert preview["blocks"] == 1 and "<<<1>>>" in preview["text"] and "Keep me" not in preview["text"]
    out = await texts.humanize(d["id"], {})
    assert out["asked"] == 1 and out["replaced"] == 0 and out["texts"] == out["previous"]
    rows = calls("text_humanize")
    assert len(rows) == 1 and refs_of(rows[0]["id"]) == design_refs(d, setup)
    assert texts.parse_markers("<<<1>>>\nOne\n<<<2>>>\nTwo") == {1: "One", 2: "Two"}

    designs.patch(d["id"], {"texts": [{"role": "headline", "text": "Keep me", "locked": True}]})
    with pytest.raises(AppError) as e:
        await texts.humanize(d["id"], {})
    assert code_of(e) == "no_text"


# ── ready layouts ───────────────────────────────────────────────────────────


def test_ready_layouts():
    items = layouts.list_layouts()
    builtin = [x for x in items if x["builtin"]]
    assert {x["code"] for x in builtin} == {"bottom_caption", "top_title", "center_card", "bottom_band",
                                            "corner_badge"}
    setup = make_frame()
    d = open_one(setup)
    card = next(x for x in builtin if x["code"] == "center_card")
    applied = designs.apply_layout(d["id"], card["id"])
    words = [x for x in applied["layers"] if x["type"] == "text"]
    assert words and {x["block_id"] for x in words} <= {t["id"] for t in d["texts"]}
    assert any(x["text"] == "Fresh coffee" for x in words)

    own = layouts.create({"title": "Mine", "layers": applied["layers"]})
    assert not own["builtin"] and own["texts"] == len(words)
    assert all("text" not in x and "block_id" not in x for x in own["layers"])
    with pytest.raises(AppError) as e:
        layouts.delete(card["id"])
    assert code_of(e) == "builtin_layout"
    with pytest.raises(AppError) as e:
        layouts.create({"title": "Nothing", "layers": []})
    assert code_of(e) == "empty_layout"
    layouts.delete(own["id"])
    assert len(layouts.list_layouts()) == len(items)


# ── new backgrounds ─────────────────────────────────────────────────────────


def test_backgrounds_are_queued_checked_and_stopped():
    setup = make_frame()
    d = open_one(setup)
    with pytest.raises(AppError) as e:
        backgrounds.start(d["id"], {"prompt": "  "})
    assert code_of(e) == "empty_prompt"
    preview = backgrounds.start(d["id"], {"prompt": "A sunny cafe", "no_lettering": True, "use_current": True,
                                          "count": 3, "preview": True})
    assert preview["text"].startswith("A sunny cafe") and len(preview["text"]) > len("A sunny cafe")
    assert preview["images"] == 1 and preview["count"] == 3 and preview["model_id"]
    plain = backgrounds.start(d["id"], {"prompt": "A sunny cafe", "preview": True})
    assert "A sunny cafe" in plain["text"] and plain["images"] == 0

    out = backgrounds.start(d["id"], {"prompt": "A sunny cafe", "count": 2})
    assert [b["status"] for b in out["backgrounds"]] == ["queued", "queued"]
    job = jobs.get(out["job_id"])
    assert job["kind"] == "text.background" and job["ref_type"] == "text_design" and job["ref_id"] == d["id"]
    with pytest.raises(AppError) as e:
        backgrounds.start(d["id"], {"prompt": "Another"})
    assert code_of(e) == "busy"
    with pytest.raises(AppError) as e:
        backgrounds.use(d["id"], out["backgrounds"][0]["id"])
    assert code_of(e) == "not_ready"

    stopped = backgrounds.cancel(d["id"])
    assert [b["status"] for b in stopped] == ["cancelled", "cancelled"]
    assert jobs.get(out["job_id"])["status"] == "cancelled"
    assert calls("text_background") == []

    # a press whose job did not live through a stop of the app
    left = backgrounds.start(d["id"], {"prompt": "Night street"})
    assert text.sweep() == 0                           # its job is still waiting
    db.update("jobs", left["job_id"], {"status": "running"})
    assert text.sweep() == 1
    row = db.get("text_backgrounds", left["backgrounds"][0]["id"])
    assert (row["status"], row["error_code"]) == ("error", "interrupted")


async def test_backgrounds_are_drawn_journaled_and_used(runner):
    setup = make_frame()
    d = open_one(setup)
    placed = (await designs.place(d["id"], {}))["design"]
    out = backgrounds.start(d["id"], {"prompt": "A sunny cafe", "count": 2, "use_current": True})
    for _ in range(500):
        rows = backgrounds.list_for(d["id"])
        if all(b["status"] not in ("queued", "running") for b in rows):
            break
        await asyncio.sleep(0.02)
    assert [b["status"] for b in rows] == ["done", "done"] and all(b["file_id"] for b in rows)
    job = jobs.get(out["job_id"])
    assert job["status"] == "done"
    assert (job["result_json"]["chat_id"], job["result_json"]["message_id"]) == (setup["chat_id"], setup["message_id"])
    drawn = calls("text_background")
    assert len(drawn) == 2 and all(refs_of(r["id"]) == design_refs(d, setup) for r in drawn)
    assert all(r["prompt_code"] == "text.background" and r["cost_usd"] > 0 for r in drawn)
    assert all(r["attachments_json"][0]["file_id"] == setup["file_id"] for r in drawn)   # the picture went along

    used = backgrounds.use(d["id"], rows[0]["id"])
    assert used["background"]["file_id"] == rows[0]["file_id"] and used["layers"] == placed["layers"]
    assert used["cost_usd"] >= sum(r["cost_usd"] for r in drawn)
    with pytest.raises(AppError) as e:
        backgrounds.use(d["id"] + 1, rows[0]["id"])
    assert code_of(e) == "not_found"


# ── prices ──────────────────────────────────────────────────────────────────


def test_every_paid_button_has_a_price():
    no_design = estimate.estimate({})
    assert set(no_design) == {"placement", "write", "variants", "humanize", "background"}
    assert no_design["background"]["refusal"] == "no_design"
    for key in ("placement", "write", "variants", "humanize"):
        assert no_design[key]["usd"] > 0 and no_design[key]["model_id"] and no_design[key]["refusal"] is None
    setup = make_frame()
    d = open_one(setup)
    one = estimate.estimate({"design_id": d["id"]})
    many = estimate.estimate({"design_id": d["id"], "variants": 3, "backgrounds": 4, "use_current": "true"})
    assert one["background"]["usd"] > 0 and one["background"]["refusal"] is None
    assert many["variants"]["count"] == 3 and many["background"]["count"] == 4
    assert many["variants"]["usd"] > one["variants"]["usd"]
    assert many["background"]["usd"] > one["background"]["usd"]
    assert estimate.estimate({"variants": 99})["variants"]["count"] == 4


# ── HTTP ────────────────────────────────────────────────────────────────────


def test_http_routes(api):
    setup = make_frame()
    r = api.post("/api/text/designs/open", json={"frame_id": setup["frame_id"], "chat_id": setup["chat_id"],
                                                 "message_id": setup["message_id"]})
    assert r.status_code == 200
    d = r.json()
    assert api.get(f"/api/text/designs/{d['id']}").json()["id"] == d["id"]
    assert err(api.get("/api/text/designs/99999")) == "not_found"
    assert err(api.post("/api/text/designs/open", json={})) == "bad_request"

    r = api.post(f"/api/text/designs/{d['id']}/place", json={})
    assert r.status_code == 200 and set(r.json()["placement"]["sources"].values()) == {"fallback"}
    r = api.patch(f"/api/text/designs/{d['id']}", json={"options": {"use_system": True, "language": "uk"}})
    assert r.json()["options"]["use_system"] is True and r.json()["options"]["language"] == "uk"
    assert err(api.patch(f"/api/text/designs/{d['id']}", json={"layers": [{"type": "video"}]})) == "bad_layer"

    r = api.get(f"/api/text/designs/{d['id']}/preview.png", params={"max_side": 200})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    report = json.loads(r.headers["x-render-report"])
    assert (report["width"], report["height"]) == (160, 200)
    assert Image.open(io.BytesIO(r.content)).size == (160, 200)

    r = api.post(f"/api/text/designs/{d['id']}/save")
    assert r.status_code == 200 and r.json()["frame"]["file_id"] == r.json()["file"]["id"]

    for path in ("write", "variants", "humanize"):
        r = api.post(f"/api/text/designs/{d['id']}/{path}", json={"preview": True, "note": "coffee"})
        assert r.status_code == 200, (path, r.text)
    assert err(api.post(f"/api/text/designs/{d['id']}/backgrounds", json={})) == "empty_prompt"
    r = api.post(f"/api/text/designs/{d['id']}/backgrounds/cancel")
    assert r.json() == {"backgrounds": []}

    r = api.get("/api/text/estimate", params={"design_id": d["id"], "variants": 2})
    assert r.json()["variants"]["count"] == 2
    items = api.get("/api/text/layouts").json()["items"]
    assert len(items) == 5
    r = api.post(f"/api/text/designs/{d['id']}/layout", json={"layout_id": items[0]["id"]})
    assert r.status_code == 200
    r = api.post("/api/text/layouts", json={"title": "Mine", "layers": r.json()["layers"]})
    own = r.json()
    assert api.delete(f"/api/text/layouts/{own['id']}").json() == {"ok": True}
    assert api.delete(f"/api/text/layouts/{items[0]['id']}").status_code == 409

    r = api.get("/api/text/fonts/google", params={"q": "roboto", "limit": 5})
    assert r.status_code == 200 and r.json()["items"][0]["family"].lower().startswith("roboto")
    assert err(api.get("/api/text/fonts/google", params={"category": "comic"})) == "bad_request"
