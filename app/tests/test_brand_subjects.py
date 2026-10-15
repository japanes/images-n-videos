"""Module 08: subjects — photos and order, describe from photos, API for studio and chat."""

import io

import pytest
from PIL import Image

from vf.core import db, files, prompts
from vf.core.errors import AppError
from vf.modules import brand
from vf.modules.brand import subjects


def png_bytes(color=(30, 120, 200), size=(80, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def add_photos(client, subject_id, n):
    out = None
    for index in range(n):
        r = client.post(f"/api/brand/subjects/{subject_id}/photos",
                        files={"file": (f"p{index}.png", png_bytes((index * 20, 50, 90)), "image/png")},
                        data={"angle": f"side {index}"})
        assert r.status_code == 200, r.text
        out = r.json()
    return out


def test_prompt_file_is_valid():
    assert prompts.check_all() == []
    pf = prompts.get("SUBJECT_DESCRIBE")
    assert pf.role == "vision_describe"
    assert pf.response == "json"
    assert set(pf.variables) == {"name", "kind", "photo_count", "focus", "existing"}
    assert pf.schema["required"] == ["description", "name"]


def test_subject_crud_photos_and_order(client):
    r = client.post("/api/brand/subjects", json={"name": "Red mug", "kind": "product"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    subject = add_photos(client, sid, 5)
    assert subject["photo_count"] == 5
    assert [p["sent"] for p in subject["photos"]] == [True, True, True, True, False]
    assert subject["cover"]["id"] == subject["photos"][0]["file_id"]

    ids = [p["id"] for p in subject["photos"]]
    r = client.put(f"/api/brand/subjects/{sid}/photos/order", json={"ids": [ids[4], ids[0]]})
    assert [p["id"] for p in r.json()["photos"]] == [ids[4], ids[0], ids[1], ids[2], ids[3]]

    r = client.patch(f"/api/brand/subject-photos/{ids[1]}", json={"angle": "  back   label "})
    assert next(p for p in r.json()["photos"] if p["id"] == ids[1])["angle"] == "back label"

    images = brand.subject_images(sid)
    assert len(images) == 4
    assert images[0]["file_id"] == r.json()["photos"][0]["file_id"]
    assert images[0]["mime"] == "image/png"

    file_id = r.json()["photos"][0]["file_id"]
    r = client.delete(f"/api/brand/subject-photos/{ids[4]}")
    assert r.json()["photo_count"] == 4
    assert db.get("files", file_id) is None

    r = client.post("/api/brand/subjects", json={"kind": "spaceship"})
    assert r.json()["error"]["code"] == "bad_kind"

    assert client.delete(f"/api/brand/subjects/{sid}").status_code == 200
    assert client.get(f"/api/brand/subjects/{sid}").status_code == 404
    assert db.fetch_value("SELECT COUNT(*) FROM files WHERE source_type = 'brand_subject'") == 0


def test_photo_limit(client):
    sid = client.post("/api/brand/subjects", json={"name": "Shoe"}).json()["id"]
    add_photos(client, sid, subjects.MAX_PHOTOS)
    r = client.post(f"/api/brand/subjects/{sid}/photos", files={"file": ("x.png", png_bytes(), "image/png")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "subject_photo_limit"


def test_one_off_and_promote(client):
    sid = client.post("/api/brand/subjects", json={"name": "Quick", "one_off": True}).json()["id"]
    lib = client.get("/api/brand/subjects").json()
    assert lib["items"] == [] and lib["counts"] == {"library": 0, "one_off": 1}
    assert [s["id"] for s in client.get("/api/brand/subjects", params={"scope": "one_off"}).json()["items"]] == [sid]
    r = client.post(f"/api/brand/subjects/{sid}/promote")
    assert r.json()["one_off"] is False
    assert [s["id"] for s in client.get("/api/brand/subjects").json()["items"]] == [sid]


def _ai_calls(purpose):
    return db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))


def test_describe_from_photos_and_manual_guard(client):
    sid = client.post("/api/brand/subjects", json={"kind": "product"}).json()["id"]

    r = client.post(f"/api/brand/subjects/{sid}/describe", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "subject_no_photos"

    add_photos(client, sid, 4)
    r = client.post(f"/api/brand/subjects/{sid}/describe", json={"focus": "the mug only"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["photos_used"] == 3
    assert out["subject"]["description"]
    assert out["subject"]["description_source"] == "photo"
    assert out["subject"]["describe_focus"] == "the mug only"
    assert out["subject"]["name"]  # suggested name taken because the subject had none
    calls = _ai_calls("subject_describe")
    assert len(calls) == 1
    assert calls[0]["prompt_code"] == "SUBJECT_DESCRIBE"
    assert calls[0]["prompt_version"] == 1
    assert calls[0]["role"] == "vision_describe"
    assert calls[0]["status"] == "success"
    refs = db.fetch_all("SELECT * FROM ai_call_refs WHERE call_id = ?", (calls[0]["id"],))
    assert ("subject", sid) in [(r["ref_type"], r["ref_id"]) for r in refs]

    # The user's name is never replaced.
    client.patch(f"/api/brand/subjects/{sid}", json={"name": "My mug"})
    r = client.post(f"/api/brand/subjects/{sid}/describe", json={})
    assert r.status_code == 200
    assert r.json()["subject"]["name"] == "My mug"

    # A hand-written description needs confirmation.
    client.patch(f"/api/brand/subjects/{sid}", json={"description": "White mug with a red handle."})
    r = client.post(f"/api/brand/subjects/{sid}/describe", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "subject_description_manual"
    assert client.get(f"/api/brand/subjects/{sid}").json()["description"] == "White mug with a red handle."
    assert len(_ai_calls("subject_describe")) == 2  # the refused call cost nothing

    r = client.post(f"/api/brand/subjects/{sid}/describe", json={"force": True})
    assert r.status_code == 200
    assert r.json()["subject"]["description_source"] == "photo"
    assert len(_ai_calls("subject_describe")) == 3


def test_describe_estimate(client):
    r = client.post("/api/estimate", json={"kind": "text", "role": "vision_describe", "input_images": 3,
                                           "purpose": "subject_describe"})
    assert r.status_code == 200, r.text
    assert r.json()["usd"] > 0


def test_generation_api(database):
    mug = subjects.create_subject("Red mug", "product", description="A red ceramic mug.")
    cap = subjects.create_subject("Cap", "prop")
    words = subjects.create_subject("Logo text", "prop", description="Only words")
    quick = subjects.create_subject("Red mug XL", "product", one_off=True)
    for _ in range(6):
        subjects.add_photo_upload(mug["id"], png_bytes(), filename="m.png")
    subjects.add_photo_upload(cap["id"], png_bytes(), filename="c.png")

    assert subjects.normalize_subject_ids([str(mug["id"]), {"id": cap["id"]}, mug["id"], "x", None]) == [
        mug["id"], cap["id"]]

    groups = brand.subject_groups([cap["id"], words["id"], mug["id"], 99999], blobs=True)
    assert [g["id"] for g in groups] == [cap["id"], mug["id"]]  # no photos -> dropped; caller order kept
    assert len(groups[1]["photos"]) == 4
    assert groups[1]["photos"][0]["blob"].mime == "image/png"

    described = brand.describe_subjects([words["id"], mug["id"]])
    assert [d["name"] for d in described] == ["Logo text", "Red mug"]

    assert brand.find_subject_by_name("red MUG")["id"] == mug["id"]
    assert brand.find_subject_by_name("Red mug XL") is None  # one-off not in the library
    assert brand.find_subject_by_name("Red mug XL", include_one_off=True)["id"] == quick["id"]

    text = "Put @red mug next to @Cap, and @Red mug XL too; email a@b"
    found = brand.match_mentions(text)
    assert [(m["id"], text[m["start"]:m["end"]]) for m in found] == [
        (mug["id"], "@red mug"), (cap["id"], "@Cap"), (mug["id"], "@Red mug")]
    found = brand.match_mentions(text, extra_ids=[quick["id"]])
    assert [m["id"] for m in found] == [mug["id"], cap["id"], quick["id"]]


def test_subject_photo_file_in_use(database):
    stored = files.save_bytes(png_bytes(), mime="image/png", name="lib.png", origin="upload")
    subject = subjects.create_subject("Bag")
    subjects.add_photo_from_file(subject["id"], stored["id"])
    with pytest.raises(AppError) as err:
        files.delete(stored["id"])
    assert err.value.details["usages"][0]["type"] == "subject"
    subjects.delete_subject(subject["id"])
    assert db.get("files", stored["id"]) is not None  # picked from the library: kept


def test_update_from_manual_text_keeps_photo_source_when_unchanged(database):
    subject = subjects.create_subject("Lamp")
    db.update("subjects", subject["id"], {"description": "AI text", "description_source": "photo"})
    same = subjects.update_subject(subject["id"], description="AI text")
    assert same["description_source"] == "photo"
    edited = subjects.update_subject(subject["id"], description="AI text, brass base")
    assert edited["description_source"] == "manual"
