"""Module 09 (avatars) over HTTP, without the job runner: the checks before
anything is paid, the photos of the person (free), the identity by hand, the
catalog, the list and the archive, the media library view of avatar files."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, settings
from vf.core.google.limiter import limiter
from vf.modules import chat

LONG = ("A man of about forty with a square jaw, short graying hair and a straight nose. " * 4).strip()


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


def png(color=(20, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 160), color).save(buf, "PNG")
    return buf.getvalue()


def create(api, **body) -> dict:
    r = api.post("/api/avatars", json={"name": "Bob", "mode": "reference", **body})
    assert r.status_code == 200, r.text
    return r.json()


def upload(api, avatar_id: int, index: int = 0, angle: str = ""):
    return api.post(f"/api/avatars/{avatar_id}/photos",
                    files={"file": (f"bob-{index}.png", png((index * 20 % 255, 80, 140)), "image/png")},
                    data={"angle": angle})


def test_checks_before_anything_is_paid(api):
    assert err(api.post("/api/avatars", json={"name": " ", "mode": "reference"})) == "avatar_name_required"
    assert err(api.post("/api/avatars", json={"name": "Bob", "mode": "magic"})) == "avatar_mode_unknown"
    r = api.post("/api/avatars", json={"name": "Bob", "mode": "description", "brief": "x" * 2001})
    assert r.status_code == 400 and err(r) == "avatar_brief_too_long"

    # «from a text»: «Describe» needs the text
    made = create(api, mode="description")
    avatar_id = made["avatar"]["id"]
    r = api.post(f"/api/avatars/{avatar_id}/describe", json={})
    assert r.status_code == 400 and err(r) == "avatar_no_brief"
    price = api.post(f"/api/avatars/{avatar_id}/estimate", json={"action": "describe"}).json()
    assert price["usd"] > 0 and price["photos"] == 0

    # «from photos»: «Describe» needs a photo; nothing to draw before the identity and the face
    made = create(api, name="Ref")
    avatar_id = made["avatar"]["id"]
    r = api.post(f"/api/avatars/{avatar_id}/describe")
    assert r.status_code == 409 and err(r) == "avatar_no_photos"
    assert err(api.post(f"/api/avatars/{avatar_id}/candidates", json={"count": 2})) == "avatar_no_identity"
    assert err(api.post(f"/api/avatars/{avatar_id}/pack", json={})) in ("avatar_no_identity", "avatar_no_face")
    assert api.get(f"/api/avatars/{avatar_id}/export").status_code == 409
    assert not db.fetch_all("SELECT id FROM ai_calls")      # not one paid call so far

    # the avatar chat is a chat of its own kind
    c = chat.get_chat(made["chat_id"])
    assert c["kind"] == "avatar" and c["title"] == "Ref"
    listed = api.get("/api/avatars").json()
    assert listed["total"] == 2 and {i["name"] for i in listed["items"]} == {"Bob", "Ref"}


def test_catalog_has_36_shots_in_9_categories(api):
    cat = api.get("/api/avatars/catalog").json()
    assert cat["count"] == 36 and len(cat["shots"]) == 36 and len(cat["categories"]) == 9
    assert cat["shots"][0]["code"] == "SHOT_01"
    assert all(s["prompt"] for s in cat["shots"])


def test_photos_of_the_person(api):
    made = create(api)
    avatar_id = made["avatar"]["id"]
    picked = files.save_bytes(png((1, 1, 1)), mime="image/png", name="lib.png", origin="upload")
    r = api.post(f"/api/avatars/{avatar_id}/photos/from-files", json={"file_ids": [picked["id"], picked["id"]]})
    assert r.status_code == 200 and len(r.json()["added"]) == 1
    first = upload(api, avatar_id, 1, "front")
    assert first.status_code == 200 and first.json()["angle"] == "front"
    for i in range(2, 12):
        assert upload(api, avatar_id, i).status_code == 200
    r = upload(api, avatar_id, 12)
    assert r.status_code == 400 and err(r) == "avatar_photo_limit"

    a = api.get(f"/api/avatars/{avatar_id}").json()
    sources = a["sources"]
    assert len(sources) == 12 and sources[0]["file_id"] == picked["id"]

    # caption and mark
    one = sources[3]
    r = api.patch(f"/api/avatars/photos/{one['id']}", json={"angle": "left profile", "marked": True})
    assert r.status_code == 200 and r.json()["angle"] == "left profile" and r.json()["marked"]

    # order
    r = api.post(f"/api/avatars/{avatar_id}/photos/order", json={"ids": [sources[-1]["id"], sources[0]["id"]]})
    assert [p["id"] for p in r.json()["sources"]][:3] == [sources[-1]["id"], sources[0]["id"], sources[1]["id"]]
    assert err(api.post(f"/api/avatars/{avatar_id}/photos/order", json={"ids": [10 ** 6]})) == "bad_order"

    # an uploaded photo is used by the avatar; removed, its file goes too
    up = sources[1]
    item = api.get(f"/api/media/files/{up['file_id']}").json()
    assert item["usage_count"] == 1 and item["usages"][0]["type"] == "avatar"
    assert item["usages"][0]["url"] == f"/chat/{made['chat_id']}"
    assert api.delete(f"/api/media/files/{up['file_id']}").status_code == 409
    assert api.delete(f"/api/avatars/photos/{up['id']}").status_code == 200
    assert api.get(f"/api/media/files/{up['file_id']}").status_code == 404

    # a picture picked from the library stays there
    assert api.delete(f"/api/avatars/photos/{sources[0]['id']}").status_code == 200
    assert api.get(f"/api/media/files/{picked['id']}").json()["usage_count"] == 0


def test_identity_by_hand_and_the_lock(api):
    made = create(api)
    avatar_id = made["avatar"]["id"]
    assert err(api.post(f"/api/avatars/{avatar_id}/identity/lock")) == "avatar_no_identity"
    r = api.put(f"/api/avatars/{avatar_id}/identity", json={"identity": LONG})
    a = r.json()
    assert r.status_code == 200 and a["identity"] == LONG and a["identity_source"] == "manual"
    assert a["state"] == "no_face"
    r = api.put(f"/api/avatars/{avatar_id}/identity", json={"identity": "x" * 6001})
    assert err(r) == "avatar_identity_too_long"

    assert api.post(f"/api/avatars/{avatar_id}/identity/lock").json()["identity_locked"]
    r = api.put(f"/api/avatars/{avatar_id}/identity", json={"identity": "Another person"})
    assert r.status_code == 409 and err(r) == "avatar_identity_locked"
    assert err(api.post(f"/api/avatars/{avatar_id}/describe", json={"force": True})) == "avatar_identity_locked"
    assert not api.post(f"/api/avatars/{avatar_id}/identity/unlock").json()["identity_locked"]

    # «Describe» asks before replacing a written text
    upload(api, avatar_id)
    r = api.post(f"/api/avatars/{avatar_id}/describe", json={})
    assert r.status_code == 409 and err(r) == "avatar_identity_exists"

    # a photo can be the face too (free): the identity gets locked, SHOT_01 shows the photo
    photo = api.get(f"/api/avatars/{avatar_id}").json()["sources"][0]
    a = api.post(f"/api/avatars/{avatar_id}/face", json={"photo_id": photo["id"]}).json()
    assert a["state"] == "face_ready" and a["identity_locked"] and a["slots"][0]["file_id"] == photo["file_id"]
    assert a["subject_id"]

    # the pack's price before the button; the export of what is ready
    est = api.post(f"/api/avatars/{avatar_id}/estimate", json={"action": "pack"}).json()
    assert est["count"] == 35 and est["usd"] > 0
    r = api.get(f"/api/avatars/{avatar_id}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"


def test_settings_archive_and_spend_names(api):
    made = create(api)
    avatar_id = made["avatar"]["id"]
    r = api.patch(f"/api/avatars/{avatar_id}", json={"name": "Robert", "candidate_count": 6, "as_subject": False})
    a = r.json()
    assert a["name"] == "Robert" and a["candidate_count"] == 6 and not a["as_subject"]
    assert chat.get_chat(made["chat_id"])["title"] == "Robert"
    assert api.patch(f"/api/avatars/{avatar_id}", json={"candidate_count": 9}).json()["candidate_count"] == 6

    a = api.post(f"/api/avatars/{avatar_id}/archive", json={}).json()
    assert a["archived_at"]
    assert api.get("/api/avatars").json()["total"] == 0
    assert api.get("/api/avatars", params={"archived": True}).json()["total"] == 1
    a = api.post(f"/api/avatars/{avatar_id}/archive", json={"archived": False}).json()
    assert not a["archived_at"]
    assert api.get("/api/avatars/999999").status_code == 404
