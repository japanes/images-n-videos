"""Module 09 (avatars), stub mode: 5 photos → «Describe» → face candidates → the
face → a pack of 36; a pack cut off by a stop of the app is finished without
paying twice; a ready avatar is a studio subject and answers to ``@name`` in any
chat; its pictures are "used" in the media library; redraw, fix, own photo."""

import asyncio
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vf.core import db, files, google, jobs, settings
from vf.core.errors import AppError
from vf.core.google import stub
from vf.core.google.limiter import limiter
from vf.modules import avatars, chat
from vf.modules.avatars import draw, export, identity, photos
from vf.modules.brand import subjects as brand_subjects
from vf.modules.chat import send
from vf.modules.spend import refs as spend_refs
from vf.modules.studio import compose as studio_compose

IDENTITY = (
    "A woman of about thirty-two, slim build, around 168 cm tall, with an oval face and a slightly long chin. "
    "Her hairline is straight with a small widow's peak, the left eyebrow sits a little higher than the right. "
    "Eyes are wide-set and almond-shaped, irises gray-green with a darker limbal ring; eyelids slightly hooded.\n\n"
    "The nose is straight with a narrow bridge and a softly rounded tip; the mouth is medium wide, the upper lip "
    "thinner than the lower, the right corner lifting more when she smiles. Fair skin with light freckles across "
    "the nose, a small mole under the left cheekbone. Dark brown wavy hair, shoulder length, parted on the left."
)


@pytest.fixture(autouse=True)
def fast(database, no_sleep, monkeypatch):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    original = stub.from_schema

    def answer(schema, prompt="", path="value"):
        # «Describe» gets a real-looking identity (the stub's "stub identity" is too short on purpose)
        if path == "value" and "MASTER IDENTITY" in prompt:
            return {"identity": IDENTITY}
        return original(schema, prompt, path)

    monkeypatch.setattr(stub, "from_schema", answer)
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


def png(color=(20, 120, 200), size=(320, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def calls(purpose: str, status: str | None = None) -> list[dict]:
    rows = db.fetch_all("SELECT * FROM ai_calls WHERE purpose = ? ORDER BY id", (purpose,))
    return [r for r in rows if status is None or r["status"] == status]


def refs_of(call_id: int) -> set[tuple[str, int]]:
    return {(r["ref_type"], r["ref_id"])
            for r in db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ?", (call_id,))}


def photo_refs(purpose: str) -> list[int]:
    """The avatar pictures the successful calls of ``purpose`` were paid for (one item per call)."""
    out = []
    for c in calls(purpose, "success"):
        out += [ref_id for ref_type, ref_id in refs_of(c["id"]) if ref_type == "avatar_photo"]
    return out


async def until(check, timeout: float = 40.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def idle() -> bool:
    return not db.fetch_value("SELECT 1 FROM jobs WHERE status IN ('queued', 'running') LIMIT 1", default=None)


async def over(message_id: int, timeout: float = 40.0) -> dict:
    """Wait until the message is no longer running and every job is over."""
    await until(lambda: db.get("chat_messages", message_id)["status"] != "running" and idle(), timeout)
    return chat.get_message(message_id)


def add_photos(avatar_id: int, count: int = 5) -> list[dict]:
    colors = [(200, 40, 40), (40, 200, 40), (40, 40, 200), (200, 200, 40), (40, 200, 200), (90, 90, 90)]
    return [photos.add_upload(avatar_id, png(colors[i % len(colors)]), f"anna-{i + 1}.png",
                              angle="front" if i == 0 else "") for i in range(count)]


async def with_face(name: str = "Anna Lee") -> dict:
    """An avatar with 5 photos, a written identity and a face picked from one candidate."""
    made = avatars.create({"name": name, "mode": "reference"})
    avatar_id = made["avatar"]["id"]
    add_photos(avatar_id)
    await over(identity.start_describe(avatar_id)["message_id"])
    started = draw.start_candidates(avatar_id, {"count": 1})
    await over(started["message_id"])
    photos.make_face(avatar_id, started["queued"][0])
    return avatars.get(avatar_id)


# ── the whole way ───────────────────────────────────────────────────────────

async def test_five_photos_a_face_and_a_pack_of_36(runner):
    made = avatars.create({"name": "Anna Lee", "mode": "reference", "brief": "Freckles, calm look."})
    a = made["avatar"]
    avatar_id, chat_id = a["id"], made["chat_id"]
    assert a["state"] == "no_identity" and len(a["slots"]) == 36 and a["slots"][0]["shot_code"] == "SHOT_01"
    assert a["counts"] == {"done": 0, "total": 36, "busy": 0, "failed": 0, "empty": 35}
    c = chat.get_chat(chat_id)
    assert c["kind"] == "avatar" and c["title"] == "Anna Lee"
    assert chat.get_message(made["message_id"])["kind"] == "avatar.card"

    sources = add_photos(avatar_id)
    assert [p["kind"] for p in sources] == ["source"] * 5 and sources[0]["angle"] == "front"
    assert not calls("avatar_identity")          # photos are free

    # «Describe»: the price first, then one paid call with 3 photos
    price = avatars.estimate(avatar_id, {"action": "describe"})
    assert price["usd"] > 0 and price["photos"] == 3 and price["model_id"]
    started = identity.start_describe(avatar_id)
    msg = await over(started["message_id"])
    assert msg["kind"] == "avatar.identity" and msg["status"] == "done"
    assert msg["data"]["applied"] and msg["data"]["identity"] == IDENTITY.replace("\n\n", "\n\n")
    a = avatars.get(avatar_id)
    assert 200 <= len(a["identity"]) <= 6000 and a["identity_source"] == "model" and a["state"] == "no_face"
    (call,) = calls("avatar_identity")
    assert call["status"] == "success" and call["prompt_code"] == "avatars.identity"
    assert {("avatar", avatar_id), ("chat", chat_id), ("chat_message", started["message_id"])} <= refs_of(call["id"])
    assert msg["cost_usd"] == pytest.approx(call["cost_usd"])

    # a second «Describe» asks before replacing the text
    with pytest.raises(AppError) as e:
        identity.start_describe(avatar_id)
    assert e.value.code == "avatar_identity_exists"

    # face candidates: drawn from the identity against the uploaded photos only
    est = avatars.estimate(avatar_id, {"action": "candidates", "count": 2})
    assert est["count"] == 2 and est["usd"] > 0 and est["time"]["seconds"] > 0
    started = draw.start_candidates(avatar_id, {"count": 2})
    msg = await over(started["message_id"])
    assert msg["kind"] == "avatar.candidates" and msg["status"] == "done"
    a = avatars.get(avatar_id)
    assert len(a["candidates"]) == 2 and all(p["status"] == "done" for p in a["candidates"])
    first = a["candidates"][0]
    assert (first["file"]["width"], first["file"]["height"]) == (864, 1152)
    master = calls("avatar_master", "success")
    assert len(master) == 2 and msg["cost_usd"] == pytest.approx(sum(m["cost_usd"] for m in master))
    sent = first["meta"]["sent"]
    assert sent and {s["file_id"] for s in sent} <= {p["file_id"] for p in a["sources"]}

    # the face: SHOT_01, the identity locked, the old face kept in the history when replaced
    a = photos.make_face(avatar_id, first["id"])
    assert a["identity_locked"] and a["state"] == "face_ready" and a["face"]["id"] == first["file_id"]
    assert a["slots"][0]["file_id"] == first["file_id"] and a["counts"]["done"] == 1
    with pytest.raises(AppError) as e:
        identity.start_describe(avatar_id, {"force": True})
    assert e.value.code == "avatar_identity_locked"
    a = photos.make_face(avatar_id, a["candidates"][1]["id"])
    a = photos.make_face(avatar_id, first["id"])
    history = db.fetch_all("SELECT status FROM avatar_photos WHERE avatar_id = ? AND kind = 'face' ORDER BY id",
                           (avatar_id,))
    assert [h["status"] for h in history] == ["archived", "archived", "done"]

    # the pack: the price and the time first, then 35 pictures (the face is the 36th)
    est = avatars.estimate(avatar_id, {"action": "pack"})
    assert est["count"] == 35 and est["usd"] > 0 and est["time"]["seconds"] > 0 and est["time"]["at_once"] == 2
    started = draw.start_pack(avatar_id)
    assert len(started["queued"]) == 35
    msg = await over(started["message_id"], timeout=90)
    assert msg["kind"] == "avatar.pack" and msg["status"] == "done"
    assert msg["data"]["model_id"] and not msg["data"].get("skipped")
    a = avatars.get(avatar_id)
    assert a["state"] == "ready" and a["counts"]["done"] == 36 and a["counts"]["empty"] == 0
    shots = calls("avatar_shot", "success")
    assert len(shots) == 35 and len(set(photo_refs("avatar_shot"))) == 35
    assert all(s["prompt_code"] == "avatars.shot" for s in shots)
    second = a["slots"][1]
    assert (second["file"]["width"], second["file"]["height"]) == (864, 1152)
    assert second["meta"]["sent"][0] == {"role": "face", "file_id": first["file_id"],
                                         "caption": second["meta"]["sent"][0]["caption"]}
    assert "Gray-green".lower() in second["prompt_text"].lower()
    assert a["cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in db.fetch_all(
        "SELECT cost_usd FROM ai_calls WHERE purpose LIKE 'avatar_%'")))

    # the ZIP: 36 pictures in pack order
    data, name = export.build_zip(avatar_id)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert len(names) == 36 and names[0].startswith("anna-lee/01-shot01") and name == f"anna-lee-{avatar_id}.zip"

    # the spend screen names the avatar and the picture
    ref = spend_refs.resolve("avatar", avatar_id)
    assert ref["title"] == "Anna Lee" and ref["link"] == f"/chat/{chat_id}" and ref["thumb_url"]
    ref = spend_refs.resolve("avatar_photo", second["id"])
    assert ref["title"] == f"Anna Lee · {second['shot_code']}" and ref["url"]


async def test_an_interrupted_pack_is_finished_without_paying_twice(runner, monkeypatch):
    a = await with_face()
    avatar_id = a["id"]
    hold = {"on": True, "shots": 0}
    original = google.generate

    async def generate(**kwargs):
        if kwargs.get("purpose") == "avatar_shot":
            hold["shots"] += 1
            if hold["on"] and hold["shots"] > 4:
                await asyncio.Event().wait()    # hangs until the app stops
        return await original(**kwargs)

    monkeypatch.setattr(google, "generate", generate)
    draw.start_pack(avatar_id)

    def status_count(status: str) -> int:
        return sum(1 for s in avatars.get(avatar_id)["slots"] if s["status"] == status and s["shot_code"] != "SHOT_01")

    await until(lambda: status_count("done") == 4 and status_count("drawing") == 2)

    # the app stops in the middle of the pack, then starts again
    await jobs.runner.stop()
    hold["on"] = False
    assert status_count("queued") == 29
    await jobs.runner.start()
    draw.sweep()        # the minute sweep: the two cut-off pictures show an error, the queue goes on
    assert status_count("error") == 2

    # «Finish N unfinished»: only the two cut-off slots, the queued ones are not sent again
    est = avatars.estimate(avatar_id, {"action": "finish"})
    assert est["count"] == 2
    finished = draw.finish(avatar_id)
    assert len(finished["queued"]) == 2
    await until(idle, timeout=90)
    a = avatars.get(avatar_id)
    assert a["state"] == "ready" and a["counts"]["done"] == 36
    paid = photo_refs("avatar_shot")
    assert len(paid) == 35 and len(set(paid)) == 35      # one paid picture per slot

    # nothing left to finish
    with pytest.raises(AppError) as e:
        draw.finish(avatar_id)
    assert e.value.code == "avatar_nothing_to_draw"


async def test_a_slot_that_got_a_picture_in_the_queue_is_not_paid_for(runner):
    a = await with_face()
    avatar_id = a["id"]
    jobs.runner.paused = "update"
    started = draw.finish(avatar_id)
    assert len(started["queued"]) == 35
    target = a["slots"][5]
    with pytest.raises(AppError) as e:          # a queued slot is busy
        photos.upload_to_slot(target["id"], png(), "own.png")
    assert e.value.code == "avatar_photo_busy"
    # it gets a picture another way while waiting (as after a restore of the database)
    own = files.save_bytes(png((1, 2, 3)), mime="image/png", name="own.png", origin="upload")
    db.update("avatar_photos", target["id"], {"file_id": own["id"]})
    jobs.runner.paused = None
    jobs.runner.wake()
    await until(idle, timeout=90)
    assert len(calls("avatar_shot", "success")) == 34
    assert avatars.get(avatar_id)["slots"][5]["file_id"] == own["id"]


# ── a ready avatar is a subject ─────────────────────────────────────────────

async def test_a_ready_avatar_is_a_studio_subject_and_answers_to_its_name(runner):
    a = await with_face("Anna Lee")
    avatar_id, face = a["id"], a["face"]["id"]
    subject_id = a["subject_id"]
    assert subject_id
    s = brand_subjects.get_subject(subject_id)
    assert s["name"] == "Anna Lee" and s["kind"] == "person" and s["cover_file_id"] == face
    assert s["photos"][0]["file_id"] == face and s["description"] == IDENTITY
    assert subject_id in [x["id"] for x in brand_subjects.list_subjects()]   # the studio's subject picker
    assert brand_subjects.subject_groups([subject_id])[0]["photos"][0]["file_id"] == face

    # «@Anna Lee» in an ordinary chat: the face goes with the picture request
    c = chat.create_chat({})
    p = send.prepare(c["id"], {"text": "@Anna Lee walking on a beach at sunset", "mode": "image"})
    assert [m["id"] for m in p.mentions] == [subject_id]
    work, frame = send.synthetic(p.image, None, text=p.text, mentions=p.mentions)
    assert work["settings_json"]["subjects"] == [subject_id]
    plan = studio_compose.plan_full(work, frame)
    assert face in [x["file_id"] for x in plan.attachments()]
    est = send.estimate(c["id"], {"text": "@Anna Lee walking on a beach at sunset", "mode": "image"})
    assert est["refusal"] is None and est["extra"]["input_images"] >= 1

    # a marked photo goes with the subject too; a new face replaces the cover
    src = a["sources"][2]
    photos.update_photo(src["id"], {"marked": True})
    s = brand_subjects.get_subject(subject_id)
    assert [x["file_id"] for x in s["photos"]] == [face, src["file_id"]]

    # «use as a subject» off → gone from the library and from @name; on → back
    avatars_store = __import__("vf.modules.avatars.store", fromlist=["update"])
    a = avatars_store.update(avatar_id, {"as_subject": False})
    assert a["subject_id"] is None and not brand_subjects.match_mentions("@Anna Lee smiling")
    with pytest.raises(AppError):
        brand_subjects.get_subject(subject_id)
    a = avatars_store.update(avatar_id, {"as_subject": True})
    assert a["subject_id"] and brand_subjects.match_mentions("@Anna Lee smiling")[0]["id"] == a["subject_id"]

    # a new name follows; the archive takes the subject away, the restore brings it back
    a = avatars_store.update(avatar_id, {"name": "Anna Smith"})
    assert brand_subjects.get_subject(a["subject_id"])["name"] == "Anna Smith"
    assert chat.get_chat(a["chat_id"])["title"] == "Anna Smith"
    a = avatars_store.archive(avatar_id, True)
    assert a["subject_id"] is None and a["archived_at"]
    assert avatars.list_avatars()["total"] == 0 and avatars.list_avatars(archived=True)["total"] == 1
    a = avatars_store.archive(avatar_id, False)
    assert a["subject_id"] and not a["archived_at"]


async def test_avatar_pictures_are_used_in_the_media_library(runner):
    a = await with_face()
    face, source = a["face"]["id"], a["sources"][0]["file_id"]
    for file_id in (face, source):
        used = [u for u in files.usages(file_id) if u["type"] == "avatar"]
        assert used == [{"type": "avatar", "id": a["id"], "title": "Anna Lee", "url": f"/chat/{a['chat_id']}"}]
        with pytest.raises(AppError) as e:
            files.delete(file_id)
        assert e.value.code == "file_in_use"

    # an unpicked candidate is used while it is shown; removed from the avatar it is free again
    started = draw.start_candidates(a["id"], {"count": 1})
    await over(started["message_id"])
    extra = avatars.get(a["id"])["candidates"][-1]
    assert [u["type"] for u in files.usages(extra["file_id"])] == ["avatar"]
    photos.delete_photo(extra["id"])
    assert files.usages(extra["file_id"]) == []
    assert files.get(extra["file_id"])      # a drawn picture stays in the library

    # a removed uploaded photo is deleted with it (nothing else uses it)
    other = a["sources"][4]
    photos.delete_photo(other["id"])
    with pytest.raises(AppError):
        files.get(other["file_id"])


# ── one shot: redraw, fix, own photo, remove ───────────────────────────────

async def test_redraw_keeps_the_old_picture_until_the_new_one_comes(runner, monkeypatch):
    a = await with_face()
    avatar_id = a["id"]
    await over(draw.start_pack(avatar_id, ["SHOT_02"])["message_id"])
    slot = avatars.get(avatar_id)["slots"][1]
    old = slot["file_id"]
    assert old and slot["status"] == "done"

    # its own wording is remembered and sent
    photos.update_photo(slot["id"], {"custom_prompt": "Standing by a window, soft morning light"})
    est = avatars.estimate(avatar_id, {"action": "redraw", "photo_id": slot["id"]})
    assert est["count"] == 1 and est["usd"] > 0

    gate = asyncio.Event()
    original = google.generate

    async def generate(**kwargs):
        await gate.wait()
        return await original(**kwargs)

    monkeypatch.setattr(google, "generate", generate)
    started = draw.redraw(slot["id"])
    await until(lambda: db.get("avatar_photos", slot["id"])["status"] == "drawing")
    assert db.get("avatar_photos", slot["id"])["file_id"] == old       # still shows the old picture
    gate.set()
    await over(started["message_id"])
    row = avatars.get(avatar_id)["slots"][1]
    assert row["file_id"] != old and row["meta"]["previous_file_ids"] == [old]
    assert "soft morning light" in row["prompt_text"] and row["custom_prompt"].startswith("Standing")
    assert files.get(old)       # the old drawn picture stays in the media library

    # «Fix»: one phrase over the current picture
    est = avatars.estimate(avatar_id, {"action": "fix", "photo_id": row["id"], "text": "Make the hair shorter"})
    assert est["count"] == 1 and est["usd"] > 0
    started = draw.fix(row["id"], "Make the hair shorter")
    msg = await over(started["message_id"])
    assert msg["data"]["fix"] == "Make the hair shorter"
    (fix_call,) = calls("avatar_fix", "success")
    assert fix_call["prompt_code"] == "avatars.fix" and ("avatar_photo", row["id"]) in refs_of(fix_call["id"])
    fixed = avatars.get(avatar_id)["slots"][1]
    assert fixed["meta"]["sent"][-1]["role"] == "edit_base" and fixed["meta"]["sent"][-1]["file_id"] == row["file_id"]
    assert fixed["prompt_text"] == "Make the hair shorter"

    # an own photo instead of the drawn shot (free), then removed: the slot stays, empty
    shown = photos.upload_to_slot(fixed["id"], png((5, 5, 5)), "mine.png")
    assert shown["origin"] == "upload" and shown["status"] == "done"
    a = photos.delete_photo(fixed["id"])
    slot = a["slots"][1]
    assert slot["file_id"] is None and slot["status"] == "empty" and slot["shot_code"] == "SHOT_02"
    with pytest.raises(AppError):
        files.get(shown["file_id"])      # the own photo is gone with it
