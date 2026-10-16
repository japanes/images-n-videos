"""Module 15 (chat) over HTTP, without background jobs: the chat list (new, recent
first, search, rename, archive), the settings and the draft of a chat, the price
on the send button and its refusals, links to results, the media library usages,
the spend refs and messages posted by other modules."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, settings
from vf.core.google.limiter import limiter
from vf.modules import chat, studio
from vf.modules.chat import messages, store
from vf.modules.spend import refs as spend_refs


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


def stored_png(color=(20, 120, 200), size=(64, 80)) -> dict:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return files.save_bytes(buf.getvalue(), mime="image/png", name="pic.png", origin="upload")


def new_chat(api, **body) -> dict:
    r = api.post("/api/chat/chats", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def estimate(api, chat_id: int, **body) -> dict:
    r = api.post(f"/api/chat/chats/{chat_id}/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── the chat list ───────────────────────────────────────────────────────────


def test_new_chat_takes_general_settings(api):
    settings.set("general.variants", 2)
    c = new_chat(api)
    assert c["title"] == "" and c["title_auto"] is True and c["kind"] == "normal" and c["mode"] == "image"
    img, vid = c["image_settings"], c["video_settings"]
    assert img["count"] == 2 and img["model_id"] and img["aspect"] == "1:1" and img["text_mode"] == "none"
    assert img["blocks"] == {"slide_position": False} and img["series"] is False
    assert vid["model_id"] and vid["duration"] and vid["sound"] is True
    assert c["draft"]["text"] == "" and c["draft"]["enhance"] is False and c["draft"]["reply"] is None
    assert c["enhance"]["model_id"] and c["enhance"]["usd"] > 0 and c["enhance"]["error"] is None
    assert c["limits"]["max_attachments"] == 10 and c["limits"]["image_roles"] == ["reference", "subject", "base"]
    assert c["limits"]["video_roles"] == ["first", "last", "reference"]
    assert c["image_blocks"]["error"] is None
    slide = next(b for b in c["image_blocks"]["items"] if b["code"] == "slide_position")
    assert slide["on"] is False and slide["default"] is True


def test_list_recent_first_search_rename_archive(api):
    a = new_chat(api)
    b = new_chat(api, title="Bread  for   the shop")
    assert b["title"] == "Bread for the shop" and b["title_auto"] is False
    store.update_chat(a["id"], {})
    messages.add_message(a["id"], type="request", kind="image", mode="image", text="Lemons on a blue plate")
    store.update_chat(a["id"], {"title": ""})
    db.update("chats", a["id"], {"title": "Lemons on a blue plate"})
    store.touch(a["id"], message=True)

    items = api.get("/api/chat/chats").json()["items"]
    assert [c["id"] for c in items] == [a["id"], b["id"]]                     # the one with a message is newer
    found = api.get("/api/chat/chats", params={"q": "blue"}).json()
    assert [c["id"] for c in found["items"]] == [a["id"]] and found["total"] == 1
    assert [c["id"] for c in api.get("/api/chat/chats", params={"q": "shop"}).json()["items"]] == [b["id"]]

    r = api.patch(f"/api/chat/chats/{b['id']}", json={"title": "Rye"})
    assert r.json()["title"] == "Rye" and r.json()["title_auto"] is False

    r = api.post(f"/api/chat/chats/{b['id']}/archive", json={"archived": True})
    assert r.json()["archived"] is True and r.json()["archived_at"]
    assert [c["id"] for c in api.get("/api/chat/chats").json()["items"]] == [a["id"]]
    assert [c["id"] for c in api.get("/api/chat/chats", params={"archived": True}).json()["items"]] == [b["id"]]
    r = api.post(f"/api/chat/chats/{b['id']}/estimate", json={"mode": "image", "text": "x"})
    assert r.json()["refusal"] == "chat_archived"
    api.post(f"/api/chat/chats/{b['id']}/archive", json={"archived": False})
    assert len(api.get("/api/chat/chats").json()["items"]) == 2

    assert api.get("/api/chat/chats/999").status_code == 404
    assert api.post("/api/chat/chats/999/estimate", json={"text": "x"}).status_code == 404


def test_title_from_first_words():
    assert store.auto_title("Bread") == "Bread"
    assert store.auto_title("one two three four five six seven") == "one two three four five six…"
    assert store.auto_title("x" * 80).endswith("…") and len(store.auto_title("x" * 80)) == 61


def test_settings_and_draft_are_kept_per_chat(api):
    c = new_chat(api)
    pic = stored_png()
    r = api.patch(f"/api/chat/chats/{c['id']}", json={
        "mode": "video", "image_settings": {"count": 4, "aspect": "9:16", "blocks": {"slide_position": True}},
        "video_settings": {"sound": False, "camera_move": ""},
        "draft": {"text": "A dog on the beach", "attachments": [{"file_id": pic["id"], "role": "first"}],
                  "enhance": True}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "video" and out["image_settings"]["count"] == 4 and out["image_settings"]["aspect"] == "9:16"
    assert out["image_settings"]["blocks"] == {} and out["video_settings"]["sound"] is False   # defaults only
    slide = next(b for b in out["image_blocks"]["items"] if b["code"] == "slide_position")
    assert slide["on"] is True
    r = api.patch(f"/api/chat/chats/{c['id']}", json={"image_settings": {"blocks": {"slide_position": False}}})
    r = api.patch(f"/api/chat/chats/{c['id']}", json={"image_settings": {"blocks": {"language": True}}})
    assert r.json()["image_settings"]["blocks"] == {"slide_position": False, "language": True}   # one at a time
    assert out["draft"]["text"] == "A dog on the beach" and out["draft"]["enhance"] is True
    assert out["draft"]["attachments"][0]["file"]["id"] == pic["id"]
    other = new_chat(api)
    assert other["image_settings"]["count"] == 3 and other["draft"]["text"] == ""

    assert err(api.patch(f"/api/chat/chats/{c['id']}", json={"image_settings": {"aspect": "7:3"}})) == "bad_aspect"
    assert err(api.patch(f"/api/chat/chats/{c['id']}", json={"mode": "audio"})) == "bad_request"
    assert err(api.patch(f"/api/chat/chats/{c['id']}", json={"image_settings": {"count": 99}})) == "bad_request"


# ── the price on the send button ────────────────────────────────────────────


def test_estimate_and_refusals(api):
    c = new_chat(api, image_settings={"count": 2})
    cid = c["id"]
    est = estimate(api, cid, mode="image", text="A red apple")
    assert est["refusal"] is None and est["action"] == "new_image" and est["count"] == 2 and est["usd"] > 0
    assert est["parts"]["enhance"] == 0 and est["model_id"]
    with_help = estimate(api, cid, mode="image", text="A red apple", enhance=True)
    assert with_help["parts"]["enhance"] > 0 and with_help["usd"] > est["usd"]

    assert estimate(api, cid, mode="image", text="  ")["refusal"] == "chat_text_empty"
    assert estimate(api, cid, mode="image", text="x" * 4001)["refusal"] == "chat_text_too_long"
    a, b = stored_png(), stored_png((200, 10, 10))
    two_firsts = [{"file_id": a["id"], "role": "first"}, {"file_id": b["id"], "role": "first"}]
    assert estimate(api, cid, mode="video", text="x", attachments=two_firsts)["refusal"] == "chat_role_twice"
    base_and_more = [{"file_id": a["id"], "role": "base"}, {"file_id": b["id"], "role": "reference"}]
    assert estimate(api, cid, mode="image", text="x", attachments=base_and_more)["refusal"] == "chat_base_alone"
    assert estimate(api, cid, mode="image", text="x",
                    attachments=[{"file_id": a["id"], "role": "first"}])["refusal"] == "chat_role_unknown"
    assert estimate(api, cid, mode="image", text="x",
                    attachments=[{"file_id": 999, "role": "reference"}])["refusal"] == "chat_attachment_missing"
    assert estimate(api, cid, text="x", reply_to=12345)["refusal"] == "chat_reply_unknown"

    base = estimate(api, cid, mode="image", text="Make it green", attachments=[{"file_id": a["id"], "role": "base"}])
    assert base["refusal"] is None and base["action"] == "edit_base" and base["count"] == 1
    refs = estimate(api, cid, mode="image", text="In this style",
                    attachments=[{"file_id": a["id"], "role": "reference"}, {"file_id": b["id"], "role": "subject"}])
    assert refs["refusal"] is None and refs["action"] == "new_image"
    video = estimate(api, cid, mode="video", text="A boat", attachments=[{"file_id": a["id"], "role": "first"}])
    assert video["refusal"] is None and video["action"] == "new_video" and video["usd"] > 0
    assert video["extra"]["seconds"] > 0


def test_reply_goes_without_pictures(api):
    c = new_chat(api)
    pic = stored_png()
    work = studio.create_work({"title": "t", "aspect": "1:1", "frame_count": 1})
    frame_id = studio.get_work(work["id"])["frames"][0]["id"]
    studio.pick_picture(frame_id, pic["id"], source="library")
    mid = messages.add_message(c["id"], type="result", kind="image", mode="image", status="done",
                               refs={"work_id": work["id"]},
                               data={"items": [{"frame_id": frame_id, "work_id": work["id"], "file_id": pic["id"],
                                                "status": "done", "job_id": None, "mode": "library"}]})
    ok = estimate(api, c["id"], text="Brighter", reply_to=mid, reply_index=0)
    assert ok["refusal"] is None and ok["action"] == "edit"
    assert estimate(api, c["id"], text="Brighter", reply_to=mid, reply_index=3)["refusal"] == "chat_item_unknown"
    bad = estimate(api, c["id"], text="Brighter", reply_to=mid,
                   attachments=[{"file_id": pic["id"], "role": "reference"}])
    assert bad["refusal"] == "chat_reply_no_pictures"


# ── links, usages, spend refs ───────────────────────────────────────────────


def test_find_a_result_with_no_chat_and_a_missing_one(api):
    work = studio.create_work({"title": "t", "aspect": "1:1", "frame_count": 1})
    frame_id = studio.get_work(work["id"])["frames"][0]["id"]
    r = api.get("/api/chat/find", params={"frame": frame_id}).json()
    assert r["chat_id"] is None and r["frame_id"] == frame_id and r["work_id"] == work["id"]
    assert api.get("/api/chat/find", params={"work": 999}).status_code == 404
    assert err(api.get("/api/chat/find")) == "bad_request"
    assert err(api.get("/api/chat/find", params={"video": "abc"})) == "bad_request"


def test_attached_picture_is_used_until_the_chat_is_archived(api):
    c = new_chat(api)
    pic, loose = stored_png(), stored_png((1, 2, 3))
    api.patch(f"/api/chat/chats/{c['id']}", json={"draft": {"attachments": [{"file_id": pic["id"]}]}})
    used = files.usages(pic["id"])
    assert used == [{"type": "chat", "id": c["id"], "title": f"#{c['id']}", "link": f"/chat/{c['id']}"}]
    assert err(api.delete(f"/api/media/files/{pic['id']}")) == "file_in_use"
    assert files.usages(loose["id"]) == []

    api.patch(f"/api/chat/chats/{c['id']}", json={"draft": {"attachments": []}})
    messages.add_message(c["id"], type="request", kind="image", mode="image", text="x",
                         attachments=[{"file_id": pic["id"], "role": "reference"}])
    assert [u["id"] for u in files.usages(pic["id"])] == [c["id"]]
    api.post(f"/api/chat/chats/{c['id']}/archive", json={"archived": True})
    assert files.usages(pic["id"]) == []


def test_spend_refs_of_a_chat_and_a_message(api):
    c = new_chat(api, title="Coffee")
    mid = messages.add_message(c["id"], type="request", kind="image", mode="image", text="A cup  of coffee")
    assert spend_refs.resolve("chat", c["id"])["title"] == "Coffee"
    ref = spend_refs.resolve("chat_message", mid)
    assert ref["title"] == "A cup of coffee" and ref["link"] == f"/chat/{c['id']}?message={mid}"
    assert spend_refs.resolve("chat_message", 999)["exists"] is False


def test_pictures_of_a_chat(api):
    c = new_chat(api)
    a, b = stored_png(), stored_png((9, 9, 9))
    messages.add_message(c["id"], type="request", kind="image", mode="image", text="x",
                         attachments=[{"file_id": a["id"], "role": "reference"}])
    messages.add_message(c["id"], type="result", kind="image", mode="image", status="done",
                         data={"items": [{"file_id": b["id"], "status": "done"},
                                         {"file_id": None, "status": "error"}]})
    items = api.get(f"/api/chat/chats/{c['id']}/pictures").json()["items"]
    assert [i["id"] for i in items] == [b["id"], a["id"]]


# ── messages of other modules (05, 06, 09) ──────────────────────────────────


def test_post_message_and_update_it(api):
    c = chat.create_chat({"kind": "avatar", "title": "Anna", "meta": {"avatar_id": 7}})
    assert c["kind"] == "avatar" and c["meta_json"] == {"avatar_id": 7}
    work = studio.create_work({"title": "t", "aspect": "1:1", "frame_count": 1})
    m = chat.post_message(c["id"], kind="avatar.card", text="Anna is ready", data={"avatar_id": 7},
                          links=[("work", work["id"])], status="running")
    assert m["kind"] == "avatar.card" and m["type"] == "service" and m["status"] == "running"
    assert m["data"] == {"avatar_id": 7} and m["position"] == 1
    assert chat.find(work=work["id"])["message_id"] == m["id"]
    done = chat.update_posted(m["id"], status="done", data={"avatar_id": 7, "photos": 4}, cost_usd=0.12)
    assert done["status"] == "done" and done["data"]["photos"] == 4 and done["cost_usd"] == 0.12
    listed = api.get(f"/api/chat/chats/{c['id']}/messages").json()["items"]
    assert [x["id"] for x in listed] == [m["id"]]
    assert api.get(f"/api/chat/messages/{m['id']}").json()["kind"] == "avatar.card"

    with pytest.raises(Exception) as exc:
        chat.post_message(c["id"], kind="Bad Kind")
    assert exc.value.code == "bad_request"
    with pytest.raises(Exception) as exc:
        chat.update_posted(m["id"], status="maybe")
    assert exc.value.code == "bad_request"


def test_messages_are_paged_oldest_first(api):
    c = new_chat(api)
    ids = [messages.add_message(c["id"], type="service", kind="note", text=str(i)) for i in range(5)]
    page = api.get(f"/api/chat/chats/{c['id']}/messages", params={"limit": 2}).json()
    assert [m["id"] for m in page["items"]] == ids[3:] and page["more"] is True
    before = page["items"][0]["position"]
    page = api.get(f"/api/chat/chats/{c['id']}/messages", params={"limit": 2, "before": before}).json()
    assert [m["id"] for m in page["items"]] == ids[1:3] and page["more"] is True
