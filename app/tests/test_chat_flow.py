"""Module 15 (chat), generation through the studio and the video modules (stub mode):
one chat goes 4 pictures → a reply that corrects one of them → «Animate» → a reply
that extends the video; a page reloaded in the middle of a generation; «Improve
prompt»; repeat; the series pilot; stop; «Take frame»; the full-screen viewer."""

import asyncio
import io

import pytest
from PIL import Image

from vf.core import db, files, jobs, settings
from vf.core.google.limiter import limiter
from vf.core.services import render
from vf.modules import chat, studio, video
from vf.modules.brand import subjects
from vf.modules.chat import messages, send, store
from vf.modules.studio import works as W
from vf.modules.studio.common import BUSY
from vf.modules.video import generate as video_generate
from vf.modules.video import runs as video_runs


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


class FakeRender:
    """The render service: probes give ``default`` seconds, outputs are tiny files."""

    def __init__(self) -> None:
        self.lengths: dict[str, float] = {}
        self.default = 8.0

    def length(self, rel: str) -> float:
        return self.lengths.setdefault(rel, self.default)

    async def probe(self, rel: str) -> dict:
        return {"duration": self.length(rel), "width": 1280, "height": 720}

    async def run(self, op: str, body: dict, *, ctx=None, progress_from=0.0, progress_to=1.0, note=None) -> dict:
        if op == "trim":
            length = body["end"] - body["start"]
        elif op == "compose":
            length = body["trim"]["end"] - body["trim"]["start"]
        elif op == "concat":
            length = sum(self.length(r) for r in body["inputs"])
        else:
            raise AssertionError(f"unexpected render op {op}")
        path = files.abs_path(body["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 256)
        self.lengths[body["output"]] = round(length, 3)
        return {"output": body["output"]}

    async def frame(self, rel: str, output: str, at="first", max_width=None) -> dict:
        path = files.abs_path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36), (10, 20, 30)).save(path, "JPEG")
        return {"output": output}


@pytest.fixture
def fake(monkeypatch):
    f = FakeRender()
    monkeypatch.setattr(render, "probe", f.probe)
    monkeypatch.setattr(render, "run", f.run)
    monkeypatch.setattr(render, "frame", f.frame)
    monkeypatch.setattr(video_generate, "_ingest", lambda file_id: None)
    return f


def png(color=(20, 120, 200), size=(64, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def stored_png(color=(20, 120, 200), size=(64, 80)) -> dict:
    return files.save_bytes(png(color, size), mime="image/png", name="pic.png", origin="upload")


def calls(purpose: str) -> list[dict]:
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


async def finished(message_id: int, timeout: float = 20.0) -> dict:
    """Read the message the way the page does until nothing in it is being made."""
    for _ in range(int(timeout / 0.02)):
        m = chat.get_message(message_id)
        if m["status"] not in ("running", "enhancing"):
            return m
        await asyncio.sleep(0.02)
    raise AssertionError(f"message {message_id} still {chat.get_message(message_id)['status']}")


async def frames_idle(*frame_ids: int, timeout: float = 15.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if all(db.get("frames", f)["status"] not in BUSY for f in frame_ids):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("frames still busy")


def new_chat(**image) -> dict:
    c = chat.create_chat({})
    if image:
        store.update_chat(c["id"], {"image_settings": image})
    return store.chat_row(c["id"])


# ── the whole way in one chat ───────────────────────────────────────────────


async def test_four_pictures_edit_one_animate_and_extend(runner, fake):
    c = new_chat(count=4, aspect="4:5")
    cid = c["id"]
    est = send.estimate(cid, {"mode": "image", "text": "A cup of coffee on a wooden table"})
    assert est["refusal"] is None and est["action"] == "new_image" and est["count"] == 4 and est["usd"] > 0

    # 1. Four variants: one studio work, four frames, placeholders first.
    out = await send.send(cid, {"mode": "image", "text": "A cup of coffee on a wooden table"})
    req, res = out["request"], out["result"]
    assert req["type"] == "request" and req["text"] == "A cup of coffee on a wooden table"
    assert req["settings"]["action"] == "new_image" and req["settings"]["image"]["count"] == 4
    assert req["settings"]["estimate_usd"] == est["usd"]
    assert res["type"] == "result" and res["request_id"] == req["id"] and len(res["data"]["items"]) == 4
    assert all(i["status"] in ("queued", "running") for i in res["data"]["items"])
    work_id = res["refs"]["work_id"]
    work = studio.get_work(work_id)
    assert work["frame_count"] == 4 and work["aspect"] == "4:5"
    assert work["settings"]["ideas_brief"] == "A cup of coffee on a wooden table"
    assert store.chat_row(cid)["title"] == "A cup of coffee on a…"          # first words, no AI

    res = await finished(res["id"])
    assert res["status"] == "done" and len({i["file_id"] for i in res["data"]["items"]}) == 4
    assert all(i["file"]["kind"] == "image" and i["cost_usd"] > 0 for i in res["data"]["items"])
    assert res["cost_usd"] == pytest.approx(sum(i["cost_usd"] for i in res["data"]["items"]))
    assert all(i["spend_link"] == f"/spend?ref_type=frame&ref_id={i['frame_id']}&period=all"
               for i in res["data"]["items"])
    drawn = calls("frame")
    assert len(drawn) == 4 and all(("work", work_id) in refs_of(c["id"]) for c in drawn)
    third = res["data"]["items"][2]

    # 2. A reply to the third picture corrects that frame in the studio.
    est = send.estimate(cid, {"text": "Make the cup red", "reply_to": res["id"], "reply_index": 2})
    assert est["action"] == "edit" and est["count"] == 1 and est["usd"] > 0
    out = await send.send(cid, {"text": "Make the cup red", "reply_to": res["id"], "reply_index": 2,
                                "mode": "video"})                         # a reply decides the mode itself
    edit_req, edit_res = out["request"], out["result"]
    assert edit_req["mode"] == "image" and edit_req["reply"]["id"] == res["id"]
    assert edit_req["reply"]["index"] == 2 and edit_req["reply"]["thumb_url"]
    assert edit_res["reply_to"] == res["id"] and edit_res["data"]["items"][0]["frame_id"] == third["frame_id"]
    edit_res = await finished(edit_res["id"])
    (edited,) = edit_res["data"]["items"]
    assert edit_res["status"] == "done" and edited["file_id"] != third["file_id"] and edited["mode"] == "edit"
    (edit_call,) = calls("frame_edit")
    assert ("frame", third["frame_id"]) in refs_of(edit_call["id"])
    again = chat.get_message(res["id"])
    assert again["data"]["items"][2]["file_id"] == third["file_id"]      # the older message keeps its picture

    # 3. «Animate»: the composer gets the picture as the first frame; Send makes the video.
    est = send.estimate(cid, {"mode": "video", "text": "Steam rises from the cup",
                              "attachments": [{"file_id": edited["file_id"], "role": "first"}]})
    assert est["refusal"] is None and est["action"] == "new_video" and est["usd"] > 0
    out = await send.send(cid, {"mode": "video", "text": "Steam rises from the cup",
                                "attachments": [{"file_id": edited["file_id"], "role": "first"}]})
    vid_req, vid_res = out["request"], out["result"]
    assert vid_req["attachments"][0]["role"] == "first" and vid_req["attachments"][0]["file"]["id"] == edited["file_id"]
    run_id = vid_res["refs"]["run_id"]
    run = video.get_run(run_id)
    assert run["first_frame_id"] == edited["file_id"] and run["brief"] == "Steam rises from the cup"
    vid_res = await finished(vid_res["id"])
    (clip,) = vid_res["data"]["items"]
    assert vid_res["status"] == "done", vid_res["error"]
    assert clip["version"] == 1 and clip["file"]["kind"] == "video" and clip["cost_usd"] > 0
    assert store.chat_row(cid)["mode"] == "video"

    # 4. A reply to the video extends it by one piece.
    fake.default = 6.0
    est = send.estimate(cid, {"text": "The camera pulls back", "reply_to": vid_res["id"]})
    assert est["action"] == "extend" and est["usd"] > 0 and est["extra"]["length_after"] > 8
    out = await send.send(cid, {"text": "The camera pulls back", "reply_to": vid_res["id"]})
    ext_res = await finished(out["result"]["id"])
    (piece,) = ext_res["data"]["items"]
    assert ext_res["status"] == "done", ext_res["error"]
    assert piece["kind"] == "extend" and piece["version"] == 2 and piece["file_id"] != clip["file_id"]
    assert out["request"]["settings"]["extend"]["seconds"] > 0
    (ext_call,) = calls("video_extend")
    assert "The camera pulls back" in ext_call["prompt_text"] and ("video_run", run_id) in refs_of(ext_call["id"])

    # The feed, oldest first; links find each result in this chat.
    feed = chat.get_chat(cid)
    listed = messages.list_messages(cid)
    assert [m["type"] for m in listed["items"]] == ["request", "result"] * 4 and listed["more"] is False
    assert feed["thumb_url"]
    hit = chat.find(frame=third["frame_id"])
    assert hit["chat_id"] == cid and hit["message_id"] == edit_res["id"]   # the newest message holding it
    assert chat.find(work=work_id)["message_id"] == edit_res["id"]        # the edit is in the same work
    assert chat.find(video=run_id) | {"chat_id": cid} == chat.find(video=run_id)
    assert {r["ref_type"] for r in db.fetch_all("SELECT ref_type FROM chat_result_refs WHERE chat_id = ?",
                                                 (cid,))} == {"work", "frame", "video_run", "video_clip"}

    # The attached picture is used by this chat in the media library.
    assert any(u["type"] == "chat" and u["id"] == cid for u in files.usages(edited["file_id"]))


async def test_reload_in_the_middle_shows_placeholders_then_results(database, fake):
    """No job runner yet: the page reads the feed while frames wait; nothing is lost."""
    c = new_chat(count=2)
    out = await send.send(c["id"], {"mode": "image", "text": "Two lemons"})
    res_id = out["result"]["id"]

    first = messages.list_messages(c["id"])["items"][-1]          # "reload": a fresh read of the feed
    assert first["id"] == res_id and first["status"] == "running"
    items = first["data"]["items"]
    assert [i["status"] for i in items] == ["queued", "queued"] and all(i["job_id"] for i in items)
    assert all(i["file"] is None for i in items)

    await jobs.runner.start()
    try:
        await frames_idle(*(i["frame_id"] for i in items))
    finally:
        await jobs.runner.stop()
        jobs.runner.paused = None
    done = messages.list_messages(c["id"])["items"][-1]          # another reload after it finished
    assert done["status"] == "done" and all(i["file"]["kind"] == "image" for i in done["data"]["items"])
    saved = db.get("chat_messages", res_id)                      # what the read found is saved
    assert saved["status"] == "done" and all(i["file_id"] for i in saved["data_json"]["items"])


async def test_restart_closes_a_request_left_improving(database):
    c = new_chat()
    mid = messages.add_message(c["id"], type="request", kind="image", mode="image", text="x", status="enhancing")
    await chat.on_startup()
    row = db.get("chat_messages", mid)
    assert row["status"] == "error" and row["error_code"] == "interrupted"


# ── «Improve prompt» ────────────────────────────────────────────────────────


async def test_improve_prompt_is_journaled_and_shown(runner):
    c = new_chat(count=1)
    plain = send.estimate(c["id"], {"mode": "image", "text": "A dog"})
    est = send.estimate(c["id"], {"mode": "image", "text": "A dog", "enhance": True})
    assert est["parts"]["enhance"] > 0 and est["usd"] == pytest.approx(plain["usd"] + est["parts"]["enhance"])

    out = await send.send(c["id"], {"mode": "image", "text": "A dog", "enhance": True})
    req = out["request"]
    snap = req["settings"]
    assert req["status"] == "done" and req["text"] == "A dog"
    assert snap["enhanced"] is True and snap["original_text"] == "A dog"
    assert snap["sent_text"].startswith("[stub answer]") and snap["enhance_prompt"] == {"code": "chat.enhance",
                                                                                         "version": 1}
    (call,) = calls("prompt_enhance")
    assert call["status"] == "success" and call["cost_usd"] > 0 and call["prompt_code"] == "chat.enhance"
    assert refs_of(call["id"]) == {("chat", c["id"]), ("chat_message", req["id"])}
    assert req["cost_usd"] == pytest.approx(call["cost_usd"]) and snap["enhance_model_id"] == call["model_id"]
    assert req["spend_link"] == f"/spend?ref_type=chat_message&ref_id={req['id']}&period=all"
    work = studio.get_work(out["result"]["refs"]["work_id"])
    assert work["settings"]["ideas_brief"] == snap["sent_text"]          # the improved text was drawn
    await finished(out["result"]["id"])

    # «Send as I wrote»: the same request again with the person's own words, a new paid generation.
    est = send.repeat_estimate(req["id"], original=True)
    assert est["refusal"] is None and est["parts"]["enhance"] == 0
    again = await send.repeat(req["id"], original=True)
    assert again["request"]["settings"]["sent_text"] == "A dog" and again["request"]["settings"]["enhanced"] is False
    work = studio.get_work(again["result"]["refs"]["work_id"])
    assert work["settings"]["ideas_brief"] == "A dog"
    assert len(calls("prompt_enhance")) == 1
    await finished(again["result"]["id"])


async def test_improve_prompt_failure_keeps_google_words_and_starts_nothing(database):
    c = new_chat(count=1)
    out = await send.send(c["id"], {"mode": "image", "text": "[stub:error=permission_denied] A cat",
                                    "enhance": True})
    req = out["request"]
    assert out["result"] is None and req["status"] == "error" and req["error_code"] == "permission_denied"
    assert "simulated permission_denied" in req["error"]
    (call,) = calls("prompt_enhance")
    assert call["status"] == "error" and refs_of(call["id"]) == {("chat", c["id"]), ("chat_message", req["id"])}
    assert db.fetch_value("SELECT COUNT(*) FROM image_works") == 0


# ── repeat, mentions, series, stop ──────────────────────────────────────────


async def test_repeat_uses_the_saved_settings_not_the_current_ones(runner):
    loaf = subjects.create_subject("Loaf", kind="product", description="Round rye loaf")
    subjects.add_photo_upload(loaf["id"], png((90, 60, 30)), filename="loaf.png")
    c = new_chat(count=1, aspect="1:1")
    out = await send.send(c["id"], {"mode": "image", "text": "@Loaf on a plate"})
    snap = out["request"]["settings"]
    assert snap["mentions"] == [{"id": loaf["id"], "name": "Loaf"}]
    first = studio.get_work(out["result"]["refs"]["work_id"])
    assert loaf["id"] in first["settings"]["subjects"]
    await finished(out["result"]["id"])

    store.update_chat(c["id"], {"image_settings": {"aspect": "9:16", "count": 3}})
    again = await send.repeat(out["result"]["id"])                       # from the result: its request
    work = studio.get_work(again["result"]["refs"]["work_id"])
    assert work["aspect"] == "1:1" and work["frame_count"] == 1 and loaf["id"] in work["settings"]["subjects"]
    assert again["request"]["settings"]["image"]["aspect"] == "1:1"
    await finished(again["result"]["id"])


async def test_series_pilot_then_accept(runner):
    c = new_chat(count=3, series=True)
    est = send.estimate(c["id"], {"mode": "image", "text": "Bread"})
    assert est["extra"]["series"] is True and est["count"] == 3
    out = await send.send(c["id"], {"mode": "image", "text": "Bread"})
    res = out["result"]
    assert [i["status"] for i in res["data"]["items"]] == ["queued", "waiting", "waiting"]
    res = await finished(res["id"])
    assert res["status"] == "done" and [i["status"] for i in res["data"]["items"]] == ["done", "waiting", "waiting"]

    price = send.accept_pilot_estimate(res["id"])
    assert price["usd"] > 0
    accepted = send.accept_pilot(res["id"])
    assert accepted["data"]["pilot_accepted"] is True and accepted["status"] == "running"
    res = await finished(res["id"])
    assert [i["status"] for i in res["data"]["items"]] == ["done"] * 3


async def test_stop_cancels_what_is_still_waiting(database):
    c = new_chat(count=2)
    out = await send.send(c["id"], {"mode": "image", "text": "Pears"})
    stopped = send.cancel(out["result"]["id"])
    assert stopped["status"] == "cancelled" and {i["status"] for i in stopped["data"]["items"]} == {"cancelled"}


async def test_failed_start_is_a_result_with_the_reason(runner):
    c = new_chat(count=1)
    out = await send.send(c["id"], {"mode": "image", "text": "[stub:blocked] A fight"})
    res = await finished(out["result"]["id"])
    assert res["status"] == "error" and res["error_code"] == "safety_blocked"
    assert res["data"]["items"][0]["spend_link"].startswith("/spend?ref_type=frame&ref_id=")


# ── pictures from a video and from the viewer ───────────────────────────────


async def test_take_frame_from_a_video_result(runner, fake):
    c = new_chat()
    out = await send.send(c["id"], {"mode": "video", "text": "A boat"})
    res = await finished(out["result"]["id"])
    assert res["status"] == "done", res["error"]
    spent = len(db.fetch_all("SELECT id FROM ai_calls"))
    pic = await send.take_frame(res["id"], {"at": "last"})
    (item,) = pic["data"]["items"]
    assert pic["reply_to"] == res["id"] and pic["data"]["action"] == "take_frame" and item["status"] == "done"
    frame = W.frame_row(item["frame_id"])
    assert frame["source"] == "video_frame" and frame["file_id"] == item["file_id"]
    assert len(db.fetch_all("SELECT id FROM ai_calls")) == spent                     # free
    assert chat.find(frame=item["frame_id"])["message_id"] == pic["id"]


async def test_viewer_result_is_added_once(runner):
    c = new_chat(count=1)
    out = await send.send(c["id"], {"mode": "image", "text": "A pear"})
    res = await finished(out["result"]["id"])
    frame_id = res["data"]["items"][0]["frame_id"]
    assert send.from_viewer(c["id"], {"frame_id": frame_id})["message"] is None      # already in the feed

    studio.start_edit(frame_id, "make it green")                                     # made in the viewer
    added = send.from_viewer(c["id"], {"frame_id": frame_id})["message"]
    assert added and added["data"]["items"][0]["mode"] == "edit"
    assert send.from_viewer(c["id"], {"frame_id": frame_id})["message"] is None      # once
    added = await finished(added["id"])
    assert added["status"] == "done" and added["data"]["items"][0]["file_id"] != res["data"]["items"][0]["file_id"]


async def test_video_draft_is_used_by_the_send(runner, fake):
    c = new_chat()
    d = send.video_draft(c["id"], {"text": "A kite on the beach"})
    assert d["run"]["brief"] == "A kite on the beach" and store.draft(store.chat_row(c["id"]))["video_run_id"] == d[
        "run_id"]
    again = send.video_draft(c["id"], {"text": "A red kite"})
    assert again["run_id"] == d["run_id"]
    out = await send.send(c["id"], {"mode": "video", "text": "A red kite on the beach"})
    assert out["result"]["refs"]["run_id"] == d["run_id"]
    assert store.draft(store.chat_row(c["id"]))["video_run_id"] is None
    await finished(out["result"]["id"])
    assert video_runs.get_run(d["run_id"])["brief"] == "A red kite on the beach"
