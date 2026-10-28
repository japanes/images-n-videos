"""Module 05 (shot ideas), stub mode: one press writes a concept and a prompt per
frame and draws the first frame; the niche research with its sources (and its
cache, and its failure that does not stop the ideas); no search at all when the
research is off; the person's own words and the dice on one card; «Draw» and
«Draw all» as studio frames in the chat; prices; stop; a set left by a stop."""

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, jobs, settings
from vf.core.google.limiter import limiter
from vf.modules import chat, ideas, library, studio
from vf.modules.chat import send, store
from vf.modules.ideas import cards, draw, estimate, scene
from vf.modules.spend import refs as spend_refs
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


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


def new_chat(**image) -> dict:
    c = chat.create_chat({})
    if image:
        store.update_chat(c["id"], {"image_settings": image})
    return store.chat_row(c["id"])


async def written(set_id: int, timeout: float = 20.0) -> dict:
    """Wait until the set's job is over (the ideas and the drawing it starts)."""
    for _ in range(int(timeout / 0.02)):
        row = db.get("ideas_sets", set_id)
        job = db.get("jobs", row["job_id"]) if row.get("job_id") else None
        if job is not None and job["status"] not in jobs.ACTIVE:
            return ideas.get_set(set_id)
        await asyncio.sleep(0.02)
    raise AssertionError(f"set {set_id} still {db.get('ideas_sets', set_id)['status']}")


async def finished(message_id: int, timeout: float = 20.0) -> dict:
    for _ in range(int(timeout / 0.02)):
        m = chat.get_message(message_id)
        if m["status"] != "running":
            return m
        await asyncio.sleep(0.02)
    raise AssertionError(f"message {message_id} still running")


async def frames_idle(*frame_ids: int, timeout: float = 15.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if all(db.get("frames", f)["status"] not in BUSY for f in frame_ids):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("frames still busy")


def first_item(axis: str) -> str:
    return next(a for a in scene.vocabulary() if a["id"] == axis)["items"][0]["id"]


# ── one press ───────────────────────────────────────────────────────────────


async def test_one_press_writes_the_concept_and_draws_the_first_frame(runner):
    c = new_chat(count=1, aspect="4:5")
    product = stored_png()
    light = first_item("light")
    body = {"chat_id": c["id"], "research": False, "draw_first": True, "scene": {"light": [light]},
            "brief": {"niche": "Craft coffee beans", "brand": "Bean & Co", "count": 3, "language": "uk",
                      "product_refs": [product["id"]], "product_note": "The pack, front side"}}
    est = estimate.write(body)
    # the research is priced next to its switch, but it is off: not in the total
    assert est["research"] is False and est["research_usd"] > 0 and est["research_cached"] is False
    assert est["ideas_usd"] > 0 and est["ideas_model_id"] and est["frame_usd"] > 0 and est["frame_refusal"] is None
    assert est["total_usd"] == pytest.approx(est["ideas_usd"] + est["frame_usd"], abs=1e-4)

    out = ideas.start(body)
    card = out["message"]
    assert card["kind"] == "ideas.concept" and card["type"] == "result" and card["status"] == "running"
    assert card["data"]["status"] == "running" and card["data"]["brief"]["niche"] == "Craft coffee beans"
    set_id = out["set"]["id"]

    s = await written(set_id)
    assert s["status"] == "done" and s["error_code"] is None and s["draw_error_code"] is None
    assert s["concept"]["name"] and s["concept"]["direction"]
    assert [i["n"] for i in s["images"]] == [1, 2] and all(i["prompt"] and i["title"] for i in s["images"])
    assert s["prompt"] == {"code": "ideas.shot_ideas", "version": 1} and s["model_id"] == est["ideas_model_id"]
    assert s["research"] is None and s["scene"] == {"light": [light]}
    job = db.get("jobs", s["job_id"])                       # the jobs page leads «Open» to the card
    assert job["ref_type"] == "ideas_set" and job["ref_id"] == set_id
    assert job["result_json"] == {"set_id": set_id, "cards": 2, "chat_id": c["id"],
                                  "message_id": card["id"]}
    assert s["pictures"][0]["role"] == "product" and s["pictures"][0]["file"]["id"] == product["id"]

    # one paid text call, journaled with the set, the chat and the card; no search anywhere
    (call,) = calls("shot_ideas")
    assert refs_of(call["id"]) == {("ideas_set", set_id), ("chat", c["id"]), ("chat_message", card["id"])}
    assert call["prompt_code"] == "ideas.shot_ideas" and call["prompt_version"] == 1
    text = call["prompt_text"]
    assert "Craft coffee beans" in text and "Bean & Co" in text and "Ukrainian" in text
    assert "1 image attached to this message" in text and "The pack, front side" in text
    assert scene.BLOCK_HEADING in text and scene._index()[light]["en"] in text
    assert calls("shot_research") == []
    assert db.fetch_value("SELECT COUNT(*) FROM ai_calls WHERE COALESCE(search_queries, 0) > 0") == 0
    assert s["cost_usd"] == pytest.approx(call["cost_usd"], abs=1e-6)

    # the cards became one studio series: the first frame is drawn now, the second waits for «Accept»
    first, second = s["images"]
    assert first["work_id"] == second["work_id"] and first["message_id"] == second["message_id"]
    work = studio.get_work(first["work_id"])
    assert work["settings"]["series"] is True and work["aspect"] == "4:5" and work["frame_count"] == 2
    assert work["settings"]["references"] == []                       # «product into the frames» was off
    assert [f["brief"] for f in W.frames_of(work["id"])] == [first["prompt"], second["prompt"]]
    pic = await finished(first["message_id"])
    assert pic["kind"] == "image" and pic["refs"]["work_id"] == work["id"]
    assert pic["data"]["action"] == "ideas" and pic["data"]["ideas_id"] == set_id
    assert [i["status"] for i in pic["data"]["items"]] == ["done", "waiting"]
    assert len(calls("frame")) == 1

    # the card in the chat is the set itself
    card = chat.get_message(card["id"])
    assert card["status"] == "done" and card["text"] == s["concept"]["name"]
    assert card["data"]["images"] == s["images"] and card["cost_usd"] == pytest.approx(s["cost_usd"])
    assert chat.find(work=work["id"])["message_id"] == pic["id"]

    # the brief's picture is in use while the chat is there; the spend screen names the set
    used = files.usages(product["id"])
    assert {"type": "ideas", "id": set_id} in [{"type": u["type"], "id": u["id"]} for u in used]
    ref = spend_refs.resolve("ideas_set", set_id)
    assert ref["title"] == s["concept"]["name"] and ref["link"] == f"/chat/{c['id']}?message={card['id']}"


async def test_product_pictures_go_into_the_frames_only_when_asked(runner):
    c = new_chat(count=1)
    product = stored_png()
    body = {"chat_id": c["id"], "draw_first": True, "product_to_frames": True,
            "brief": {"niche": "Tea", "product_refs": [product["id"]]}}
    out = ideas.start(body)
    s = await written(out["set"]["id"])
    assert s["options"] == {"draw_first": True, "product_to_frames": True}
    work = studio.get_work(s["images"][0]["work_id"])
    assert work["settings"]["references"] == [product["id"]]
    await finished(s["images"][0]["message_id"])


# ── the niche research ──────────────────────────────────────────────────────


async def test_research_shows_its_sources_and_is_reused_from_the_cache(runner):
    c = new_chat()
    body = {"chat_id": c["id"], "research": True, "brief": {"niche": "Handmade soap", "platform": "Instagram"}}
    est = estimate.write(body)
    assert est["research"] is True and est["research_usd"] > 0 and est["research_cached"] is False
    assert est["frame_usd"] > 0 and est["draw_first"] is False             # priced, but off: not in the total
    assert est["total_usd"] == pytest.approx(est["ideas_usd"] + est["research_usd"], abs=1e-4)

    out = ideas.start(body)
    s = await written(out["set"]["id"])
    assert s["status"] == "done"
    r = s["research"]
    assert r["done"] and r["summary"] and r["cached"] is False and r["error_code"] is None
    assert r["sources"] == [{"title": "Example source (stub)", "url": "https://example.com/"}]
    (found,) = calls("shot_research")
    assert found["search_queries"] >= 1 and found["prompt_code"] == "ideas.research"
    assert ("ideas_set", s["id"]) in refs_of(found["id"]) and ("chat", c["id"]) in refs_of(found["id"])
    assert "Handmade soap" in found["prompt_text"] and "Instagram" in found["prompt_text"]
    (written_call,) = calls("shot_ideas")
    assert "NICHE: Handmade soap" in written_call["prompt_text"] and r["summary"][:40] in written_call["prompt_text"]
    assert s["cost_usd"] == pytest.approx(found["cost_usd"] + written_call["cost_usd"], abs=1e-6)
    assert all(i["work_id"] is None for i in s["images"])                 # «draw the first frame» was off
    assert calls("frame") == []

    # the same niche again (other spelling): free, from the cache, with the same links
    again = {"chat_id": c["id"], "research": True, "brief": {"niche": "  handmade   SOAP ", "platform": "instagram"}}
    est = estimate.write(again)
    assert est["research_cached"] is True and est["research_usd"] == 0 and est["research_cached_at"]
    out = ideas.start(again)
    s2 = await written(out["set"]["id"])
    assert s2["research"]["cached"] is True and s2["research"]["sources"] == r["sources"]
    assert s2["research"]["cost_usd"] == 0 and len(calls("shot_research")) == 1

    # 0 days in the settings: every set searches again
    settings.set("ideas.research_cache_days", 0)
    assert estimate.write(again)["research_usd"] > 0


async def test_a_failed_research_does_not_stop_the_ideas(runner, monkeypatch):
    real = library.render_layer

    def failing(code, values):
        text = real(code, values)
        return text + " [stub:error=permission_denied]" if code == "SHOT_RESEARCH_INPUT" else text

    monkeypatch.setattr(library, "render_layer", failing)
    c = new_chat()
    out = ideas.start({"chat_id": c["id"], "research": True, "brief": {"niche": "Candles"}})
    s = await written(out["set"]["id"])
    assert s["status"] == "done" and len(s["images"]) == 2
    assert s["research"]["error_code"] == "permission_denied" and "simulated" in s["research"]["error"]
    assert s["research"]["summary"] == "" and s["research"]["sources"] == []
    (failed,) = calls("shot_research")
    assert failed["status"] == "error"
    (written_call,) = calls("shot_ideas")
    assert "NICHE: Candles" not in written_call["prompt_text"]
    assert db.fetch_value("SELECT COUNT(*) FROM ideas_research") == 0      # nothing cached


async def test_failed_ideas_close_the_card_with_googles_words(runner):
    c = new_chat()
    out = ideas.start({"chat_id": c["id"], "draw_first": True,
                       "brief": {"niche": "[stub:error=permission_denied] Shoes"}})
    s = await written(out["set"]["id"])
    assert s["status"] == "error" and s["error_code"] == "permission_denied" and "simulated" in s["error"]
    assert s["images"] == [] and calls("frame") == []
    card = chat.get_message(out["message"]["id"])
    assert card["status"] == "error" and card["error_code"] == "permission_denied"
    (failed,) = calls("shot_ideas")
    assert failed["status"] == "error" and ("ideas_set", s["id"]) in refs_of(failed["id"])


# ── the cards ───────────────────────────────────────────────────────────────


async def test_own_words_and_the_dice_on_one_card(runner):
    c = new_chat()
    picture = stored_png()
    out = ideas.start({"chat_id": c["id"], "brief": {"niche": "Honey", "visual_refs": [picture["id"]]},
                       "scene": {"surface": [first_item("surface")]}})
    s = await written(out["set"]["id"])

    s = cards.edit(s["id"], 1, {"prompt": "  A jar of honey   on a slate\n\n  board  ", "title": " Jar "})
    assert s["images"][0]["prompt"] == "A jar of honey on a slate\nboard" and s["images"][0]["title"] == "Jar"
    assert s["images"][0]["edited"] is True and s["images"][1]["edited"] is False
    with pytest.raises(Exception) as empty:
        cards.edit(s["id"], 1, {"prompt": "   "})
    assert empty.value.code == "ideas_prompt_empty"
    with pytest.raises(Exception) as unknown:
        cards.edit(s["id"], 9, {"prompt": "x"})
    assert unknown.value.code == "ideas_card_unknown" and unknown.value.status == 404

    price = estimate.reroll(s["id"])
    assert price["usd"] > 0 and price["model_id"]
    cost_before = s["cost_usd"]
    s = await cards.reroll(s["id"], 2)
    assert s["images"][1]["prompt"] == "stub prompt" and s["images"][1]["edited"] is False
    assert s["images"][0]["prompt"] == "A jar of honey on a slate\nboard"     # the other card is kept
    (dice,) = calls("shot_idea_frame")
    assert dice["prompt_code"] == "ideas.frame_idea" and refs_of(dice["id"]) >= {("ideas_set", s["id"]), ("chat", c["id"])}
    assert "A jar of honey on a slate" in dice["prompt_text"] and "Honey" in dice["prompt_text"]
    assert "1 image attached to this message" in dice["prompt_text"]
    assert s["cost_usd"] == pytest.approx(cost_before + dice["cost_usd"], abs=1e-6)
    assert calls("shot_research") == []


async def test_draw_one_card_then_all_and_an_edit_reaches_the_waiting_frame(runner):
    c = new_chat(count=4)
    out = ideas.start({"chat_id": c["id"], "brief": {"niche": "Sneakers", "count": 2}})
    s = await written(out["set"]["id"])
    assert all(i["work_id"] is None for i in s["images"])

    # «Draw» on the second card: one frame, not a series
    price = draw.estimate(s["id"], [2])
    assert price["count"] == 1 and price["series"] is False and price["usd"] > 0 and price["refusal"] is None
    one = draw.draw(s["id"], [2])
    pic = one["message"]
    assert pic["kind"] == "image" and len(pic["data"]["items"]) == 1 and pic["data"]["series"] is False
    card = one["set"]["images"][1]
    assert card["work_id"] == pic["refs"]["work_id"] and card["message_id"] == pic["id"] and card["drawn_at"]
    assert db.get("frames", card["frame_id"])["brief"] == card["prompt"]
    assert one["set"]["images"][0]["work_id"] is None
    pic = await finished(pic["id"])
    assert pic["status"] == "done" and pic["data"]["items"][0]["file_id"]

    # «Draw all»: a series, the pilot is paid now, the rest after «Accept»
    price = draw.estimate(s["id"], "all")
    assert price["count"] == 2 and price["series"] is True
    assert price["usd_all"] == pytest.approx(price["usd"] * 2, abs=1e-4)
    every = draw.draw(s["id"], "all")
    pic = every["message"]
    assert [i["status"] for i in pic["data"]["items"]] == ["queued", "waiting"]
    first, second = every["set"]["images"]
    assert first["work_id"] == second["work_id"] == pic["refs"]["work_id"]

    # an edit of the second card goes to its frame while it waits
    cards.edit(s["id"], 2, {"prompt": "Sneakers on wet asphalt at night"})
    assert db.get("frames", second["frame_id"])["brief"] == "Sneakers on wet asphalt at night"
    pic = await finished(pic["id"])
    assert [i["status"] for i in pic["data"]["items"]] == ["done", "waiting"]
    send.accept_pilot(pic["id"])
    pic = await finished(pic["id"])
    assert [i["status"] for i in pic["data"]["items"]] == ["done", "done"]
    await frames_idle(first["frame_id"], second["frame_id"])
    assert "Sneakers on wet asphalt at night" in db.get("frames", second["frame_id"])["prompt_text"]

    # a drawn frame keeps its picture: a later edit changes only the card
    drawn_file = db.get("frames", second["frame_id"])["file_id"]
    cards.edit(s["id"], 2, {"prompt": "Something else"})
    frame = db.get("frames", second["frame_id"])
    assert frame["file_id"] == drawn_file and frame["brief"] == "Sneakers on wet asphalt at night"


async def test_draw_waits_for_the_ideas(database):
    c = new_chat()
    out = ideas.start({"chat_id": c["id"], "brief": {"niche": "Bread"}})       # no runner: the job waits
    with pytest.raises(Exception) as early:
        draw.draw(out["set"]["id"], "all")
    assert early.value.code == "ideas_not_ready"
    with pytest.raises(Exception) as early:
        cards.edit(out["set"]["id"], 1, {"prompt": "x"})
    assert early.value.code == "ideas_not_ready"


# ── stop, and a set left by a stop of the app ───────────────────────────────


def test_stop_before_the_job_starts(api):
    c = new_chat()
    r = api.post("/api/ideas/sets", json={"chat_id": c["id"], "brief": {"niche": "Wine"}})
    assert r.status_code == 200
    set_id = r.json()["set"]["id"]
    r = api.post(f"/api/ideas/sets/{set_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["error_code"] == "cancelled"
    card = chat.get_message(r.json()["message_id"])
    assert card["status"] == "cancelled"
    assert calls("shot_ideas") == []


def test_sweep_closes_a_set_whose_job_did_not_survive(database):
    c = new_chat()
    out = ideas.start({"chat_id": c["id"], "brief": {"niche": "Cheese"}})
    set_id = out["set"]["id"]
    assert ideas.sweep() == 0                                   # a queued job still runs after the start
    db.update("jobs", out["set"]["job_id"], {"status": "running"})
    assert ideas.sweep() == 1
    s = ideas.get_set(set_id)
    assert s["status"] == "error" and s["error_code"] == "interrupted"
    assert chat.get_message(out["message"]["id"])["status"] == "error"


# ── HTTP: checks, the setting, prices ───────────────────────────────────────


def test_brief_and_scene_are_checked(api):
    c = new_chat()
    video = files.save_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64, mime="video/mp4", name="v.mp4",
                             origin="upload")

    def start(**over):
        body = {"chat_id": c["id"], "brief": {"niche": "Tea"}}
        body.update(over)
        return api.post("/api/ideas/sets", json=body)

    assert err(start(brief={"niche": "   "})) == "ideas_niche_empty"
    assert err(start(brief={"niche": "Tea", "count": 11})) == "ideas_bad_count"
    assert err(start(brief={"niche": "Tea", "language": "de"})) == "ideas_bad_language"
    assert err(start(brief={"niche": "Tea", "visual_refs": [video["id"]]})) == "ideas_not_a_picture"
    many = [stored_png((i, i, i))["id"] for i in range(7)]
    assert err(start(brief={"niche": "Tea", "product_refs": many})) == "ideas_too_many_pictures"
    assert err(start(scene={"light": ["no_such_light"]})) == "ideas_scene_unknown"
    assert err(start(research="yes")) == "bad_request"
    assert start(chat_id=99999).status_code == 404
    assert db.fetch_value("SELECT COUNT(*) FROM ideas_sets") == 0
    assert api.get("/api/ideas/sets/12345").status_code == 404


def test_scene_route_and_the_dice(api):
    r = api.get("/api/ideas/scene")
    axes = r.json()["axes"]
    assert [a["id"] for a in axes] == ["surface", "backdrop", "light", "camera", "atmosphere", "props",
                                       "palette", "state"]
    assert next(a for a in axes if a["id"] == "props")["max"] == 2 and "scene" not in r.json()
    rolled = api.get("/api/ideas/scene", params={"roll": True, "seed": 7}).json()["scene"]
    assert {"surface", "backdrop", "light", "camera"} <= set(rolled)
    assert rolled == scene.roll(7) and all(len(v) == 1 for v in rolled.values())
    assert scene.normalize(rolled) == rolled


def test_prices_from_the_window(api):
    c = new_chat()
    r = api.post("/api/ideas/estimate", json={"brief": {"niche": ""}, "research": False})
    assert r.status_code == 200 and r.json()["ideas_usd"] > 0 and r.json()["research_usd"] > 0
    assert r.json()["total_usd"] == r.json()["ideas_usd"] and r.json()["frame_usd"] == 0      # no chat: no frame
    with_pictures = api.post("/api/ideas/estimate", json={"brief": {"niche": "x", "product_refs": [1, 2, 3]}}).json()
    assert with_pictures["ideas_usd"] >= r.json()["ideas_usd"]
    assert err(api.post("/api/ideas/estimate", json={"draw_first": True})) == "bad_request"
    first = api.post("/api/ideas/estimate", json={"chat_id": c["id"], "draw_first": True}).json()
    assert first["frame_usd"] > 0 and first["frame_model_id"]
