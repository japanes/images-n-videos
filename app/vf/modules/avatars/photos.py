"""The avatar's pictures that cost nothing: uploads, captions, marks, order,
removing a picture, and «Make this photo the face».

Uploaded files are dropped when nothing uses them any more; generated pictures
(paid for) are never deleted here — once no slot shows them they stay in the
media library, where the person may delete them.
"""

from __future__ import annotations

from typing import Any

from vf.core import db, files
from vf.core.errors import AppError
from vf.modules.avatars import store
from vf.modules.avatars.common import (
    BUSY,
    FACE_CODE,
    MAX_ANGLE,
    MAX_CUSTOM_PROMPT,
    MAX_SOURCE_PHOTOS,
    MAX_TITLE,
    SOURCE_PHOTO,
    clean_lines,
    clean_text,
    log,
)

# ── files ───────────────────────────────────────────────────────────────────

def drop_file(file_id: int | None) -> None:
    """Delete an uploaded file once no avatar picture shows it and nothing else uses it."""
    if not file_id:
        return
    if db.fetch_value("SELECT 1 FROM avatar_photos WHERE file_id = ? LIMIT 1", (file_id,), default=None):
        return
    try:
        row = files.get(file_id)
    except AppError:
        return
    if row.get("source_type") != SOURCE_PHOTO:
        return   # generated pictures and files picked from elsewhere stay in the media library
    try:
        files.delete(file_id)
    except AppError as exc:
        if exc.code != "file_in_use":
            raise
        log.info("avatar file %s is still used elsewhere, kept", file_id)


def _check_image_file(file_id: Any) -> dict:
    from vf.modules.studio.common import image_file

    return image_file(file_id)


def _check_free(row: dict) -> None:
    if row["status"] in BUSY:
        raise AppError("avatar_photo_busy", 409, "The picture is being drawn; wait or stop it")


def _room(avatar_id: int, adding: int) -> None:
    have = len(store.photos_of(avatar_id, "source"))
    if have + adding > MAX_SOURCE_PHOTOS:
        raise AppError("avatar_photo_limit", 400, f"An avatar can have up to {MAX_SOURCE_PHOTOS} photos",
                       max=MAX_SOURCE_PHOTOS, have=have)


def _next_sort(avatar_id: int, kind: str) -> int:
    return int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) + 1 FROM avatar_photos WHERE avatar_id = ? AND kind = ?",
                              (avatar_id, kind), default=1))


def _insert_source(avatar_id: int, file_id: int, angle: str = "", title: str = "") -> int:
    now = db.now()
    return db.insert("avatar_photos", {
        "avatar_id": avatar_id, "kind": "source", "file_id": file_id, "title": clean_text(title, MAX_TITLE),
        "angle": clean_text(angle, MAX_ANGLE), "sort": _next_sort(avatar_id, "source"), "origin": "upload",
        "status": "done", "created_at": now, "updated_at": now,
    })


# ── sources ─────────────────────────────────────────────────────────────────

def add_upload(avatar_id: Any, data: bytes, name: str | None, angle: str = "") -> dict:
    """One uploaded photo of the person (free). The browser has already made it smaller."""
    from vf.modules.studio.common import check_image

    avatar = store.avatar_row(avatar_id)
    _room(avatar["id"], 1)
    mime = check_image(data, name)
    saved = files.save_bytes(data, mime=mime, name=name or "photo", origin="upload", source_type=SOURCE_PHOTO,
                             source_id=avatar["id"], title=f"{avatar['name']} · {clean_text(name, 80) or 'photo'}")
    photo_id = _insert_source(avatar["id"], saved["id"], angle, name or "")
    store.touch(avatar["id"])
    _changed(avatar["id"])
    return store.photo_public(store.photo_row(photo_id))


def add_from_files(avatar_id: Any, file_ids: Any) -> dict:
    """Pictures already stored (the chat draft, the media library) become photos of the person."""
    avatar = store.avatar_row(avatar_id)
    if not isinstance(file_ids, list) or not file_ids:
        raise AppError("bad_request", 400, "file_ids must be a non-empty list")
    rows = [_check_image_file(fid) for fid in file_ids[:MAX_SOURCE_PHOTOS + 1]]
    have = {p["file_id"] for p in store.photos_of(avatar["id"], "source")}
    rows = [r for i, r in enumerate(rows) if r["id"] not in have and r["id"] not in {x["id"] for x in rows[:i]}]
    _room(avatar["id"], len(rows))
    added = []
    with db.tx():
        for r in rows:
            added.append(_insert_source(avatar["id"], r["id"], "", r.get("title") or r.get("original_name") or ""))
    store.touch(avatar["id"])
    _changed(avatar["id"])
    return {"added": added, "avatar": store.get(avatar["id"])}


def reorder(avatar_id: Any, ids: Any) -> dict:
    avatar = store.avatar_row(avatar_id)
    if not isinstance(ids, list):
        raise AppError("bad_order", 400, "ids must be a list of photo ids")
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError) as exc:
        raise AppError("bad_order", 400, "ids must be a list of photo ids") from exc
    own = [p["id"] for p in store.photos_of(avatar["id"], "source")]
    unknown = [i for i in ids if i not in own]
    if unknown:
        raise AppError("bad_order", 400, "These photos are not this avatar's", ids=unknown)
    with db.tx():
        for index, photo_id in enumerate([*ids, *[i for i in own if i not in ids]]):
            store.set_photo(photo_id, {"sort": index + 1})
    store.touch(avatar["id"])
    _changed(avatar["id"])
    return store.get(avatar["id"])


# ── any picture ─────────────────────────────────────────────────────────────

def update_photo(photo_id: Any, body: Any) -> dict:
    """Caption (angle), mark («send with every shot»), title, a shot's own wording."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    row = store.photo_row(photo_id)
    values: dict[str, Any] = {}
    if "angle" in body:
        values["angle"] = clean_text(body["angle"], MAX_ANGLE)
    if "title" in body and row["kind"] != "shot":
        values["title"] = clean_text(body["title"], MAX_TITLE)
    if "marked" in body:
        if row["kind"] not in ("source", "shot") or row.get("shot_code") == FACE_CODE:
            raise AppError("avatar_mark_not_allowed", 400, "Only photos and shots can be marked")
        values["marked"] = 1 if body["marked"] else 0
    if "custom_prompt" in body:
        if row["kind"] != "shot":
            raise AppError("bad_request", 400, "Only a shot has its own wording")
        text = clean_lines(str(body["custom_prompt"] or ""))
        if len(text) > MAX_CUSTOM_PROMPT:
            raise AppError("avatar_prompt_too_long", 400, "The shot wording is too long", max=MAX_CUSTOM_PROMPT)
        values["custom_prompt"] = text or None
    if values:
        store.set_photo(row["id"], values)
        store.touch(row["avatar_id"])
        _changed(row["avatar_id"], subject_too="marked" in values or "angle" in values)
    return store.photo_public(store.photo_row(row["id"]))


def delete_photo(photo_id: Any) -> dict:
    """A photo or a candidate goes away; a shot loses its picture but the slot stays.
    The face itself cannot be removed (pick another face instead)."""
    row = store.photo_row(photo_id)
    _check_free(row)
    avatar = store.avatar_row(row["avatar_id"])
    if row["kind"] == "face" or (row["kind"] == "shot" and row.get("shot_code") == FACE_CODE):
        raise AppError("avatar_face_slot", 409, "The face is chosen from the candidates or the photos")
    file_id = row.get("file_id")
    if row["kind"] == "shot":
        store.set_photo(row["id"], {"file_id": None, "status": "empty", "origin": "generated", "error_code": None,
                                    "error_text": None, "marked": 0, "job_id": None, "drawing_since": None})
    else:
        db.delete("avatar_photos", row["id"])
    store.touch(avatar["id"])
    _changed(avatar["id"], subject_too=True)   # the subject lets go of the file first
    drop_file(file_id)
    return store.get(avatar["id"])


def upload_to_slot(photo_id: Any, data: bytes, name: str | None) -> dict:
    """The person's own photo instead of a drawn shot (free)."""
    from vf.modules.studio.common import check_image

    row = store.photo_row(photo_id)
    if row["kind"] != "shot":
        raise AppError("bad_request", 400, "Only a shot slot takes an own photo")
    if row.get("shot_code") == FACE_CODE:
        raise AppError("avatar_face_slot", 409, "The face is chosen from the candidates or the photos")
    _check_free(row)
    avatar = store.avatar_row(row["avatar_id"])
    mime = check_image(data, name)
    saved = files.save_bytes(data, mime=mime, name=name or "shot", origin="upload", source_type=SOURCE_PHOTO,
                             source_id=avatar["id"], title=f"{avatar['name']} · {row['shot_code']}")
    old = row.get("file_id")
    store.set_photo(row["id"], {"file_id": saved["id"], "status": "done", "origin": "upload", "error_code": None,
                                "error_text": None, "prompt_text": None})
    store.touch(avatar["id"])
    _changed(avatar["id"], subject_too=bool(row.get("marked")))
    drop_file(old)
    return store.photo_public(store.photo_row(row["id"]))


# ── the face ────────────────────────────────────────────────────────────────

def make_face(avatar_id: Any, photo_id: Any) -> dict:
    """This picture is the face from now on: it becomes SHOT_01 and the identity is locked.
    The previous face goes to the history (archived), its file stays."""
    avatar = store.avatar_row(avatar_id)
    row = store.photo_row(photo_id)
    if row["avatar_id"] != avatar["id"]:
        raise AppError("avatar_photo_foreign", 404, "The picture belongs to another avatar")
    if not (avatar.get("identity") or "").strip():
        raise AppError("avatar_no_identity", 409, "Describe the person first")
    if not row.get("file_id") or row["status"] in BUSY:
        raise AppError("avatar_no_picture", 409, "The picture is not ready")
    file_id = row["file_id"]
    if avatar.get("face_file_id") == file_id:
        return store.get(avatar["id"])
    now = db.now()
    with db.tx():
        db.execute("UPDATE avatar_photos SET status = 'archived', updated_at = ? "
                   "WHERE avatar_id = ? AND kind = 'face' AND status != 'archived'", (now, avatar["id"]))
        db.insert("avatar_photos", {
            "avatar_id": avatar["id"], "kind": "face", "file_id": file_id, "origin": "face", "status": "done",
            "title": row.get("title") or "", "sort": _next_sort(avatar["id"], "face"),
            "meta_json": {"from_photo_id": row["id"], "from_kind": row["kind"]}, "created_at": now, "updated_at": now,
        })
        store.ensure_slots(avatar["id"])
        face_slot = store.slot(avatar["id"], FACE_CODE)
        if face_slot:
            store.set_photo(face_slot["id"], {"file_id": file_id, "origin": "face", "status": "done",
                                              "error_code": None, "error_text": None, "job_id": None,
                                              "drawing_since": None})
        if row["kind"] == "candidate":
            store.set_photo(row["id"], {"meta_json": {**(row.get("meta_json") or {}), "picked": True}})
        store.touch(avatar["id"], {"face_file_id": file_id, "identity_locked": 1})
    _changed(avatar["id"], subject_too=True)
    return store.get(avatar["id"])


def _changed(avatar_id: int, *, subject_too: bool = False) -> None:
    from vf.modules.avatars import subject

    if subject_too:
        subject.sync(avatar_id)
    store.announce(avatar_id)


__all__ = ["add_from_files", "add_upload", "delete_photo", "drop_file", "make_face", "reorder",
           "update_photo", "upload_to_slot"]
