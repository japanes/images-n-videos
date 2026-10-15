"""Subjects: a product, a person or a prop that must look recognizable in a picture.

A subject has up to 12 photos in a user-chosen order (the first 4 are sent to
the image model, so the order matters), a caption ("angle") per photo, and a
text description written by hand or by "describe from photos".

One-off subjects are made for a single work from the picker; "move to library"
turns them into normal ones (one way only).
"""

from __future__ import annotations

import re
from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.modules.brand.common import (
    IMAGE_MIMES,
    SOURCE_SUBJECT,
    check_image,
    clean_block,
    clean_text,
    drop_own_file,
    publish,
    save_upload,
)

KINDS = ("product", "person", "prop")
DESCRIPTION_SOURCES = ("manual", "photo")
SCOPES = ("library", "one_off", "all")

MAX_PHOTOS = 12  # stored per subject
PHOTOS_SENT = 4  # sent to the image model per subject, in order
MAX_NAME = 120
MAX_ANGLE = 60
MAX_DESCRIPTION = 2000  # a hand-written description; describe-from-photos keeps to 1200
MAX_FOCUS = 300
MAX_SUBJECTS_PER_REQUEST = 50


# ── reading ─────────────────────────────────────────────────────────────────


def _row(subject_id: int) -> dict:
    row = db.get("subjects", subject_id)
    if row is None:
        raise NotFound("subject", id=subject_id)
    return row


def _photo_row(photo_id: int) -> dict:
    row = db.get("subject_photos", photo_id)
    if row is None:
        raise NotFound("subject_photo", id=photo_id)
    return row


def _photos(subject_id: int) -> list[dict]:
    return db.fetch_all("SELECT * FROM subject_photos WHERE subject_id = ? ORDER BY sort, id", (subject_id,))


def _file_public(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    try:
        return files.public(files.get(file_id))
    except AppError:
        return None


def subject_public(row: dict) -> dict:
    photos = _photos(row["id"])
    cover_id = row["cover_file_id"] if any(p["file_id"] == row["cover_file_id"] for p in photos) else None
    cover_id = cover_id or (photos[0]["file_id"] if photos else None)
    return {
        "id": row["id"], "name": row["name"], "kind": row["kind"], "description": row["description"],
        "description_source": row["description_source"], "describe_focus": row["describe_focus"],
        "one_off": bool(row["one_off"]), "sort": row["sort"], "cover_file_id": cover_id,
        "cover": _file_public(cover_id),
        "photos": [{"id": p["id"], "file_id": p["file_id"], "angle": p["angle"], "sort": p["sort"],
                    "sent": index < PHOTOS_SENT, "file": _file_public(p["file_id"])}
                   for index, p in enumerate(photos)],
        "photo_count": len(photos), "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_subjects(scope: str = "library", q: str | None = None, kind: str | None = None) -> list[dict]:
    if scope not in SCOPES:
        raise AppError("bad_scope", 400, "scope must be library, one_off or all")
    sql = "SELECT * FROM subjects WHERE 1 = 1"
    params: list[Any] = []
    if scope != "all":
        sql += " AND one_off = ?"
        params.append(1 if scope == "one_off" else 0)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if q and q.strip():
        sql += " AND (name LIKE ? OR description LIKE ?)"
        like = f"%{q.strip()}%"
        params += [like, like]
    sql += " ORDER BY sort, id"
    return [subject_public(r) for r in db.fetch_all(sql, params)]


def counts() -> dict:
    rows = db.fetch_all("SELECT one_off, COUNT(*) AS n FROM subjects GROUP BY one_off")
    by = {bool(r["one_off"]): r["n"] for r in rows}
    return {"library": by.get(False, 0), "one_off": by.get(True, 0)}


def get_subject(subject_id: int) -> dict:
    """A subject with its photos (raises not_found)."""
    return subject_public(_row(subject_id))


# ── writing ─────────────────────────────────────────────────────────────────


def _touch(subject_id: int, values: dict | None = None) -> None:
    db.update("subjects", subject_id, {**(values or {}), "updated_at": db.now()})


def create_subject(name: str = "", kind: str = "product", *, description: str = "", one_off: bool = False) -> dict:
    if kind not in KINDS:
        raise AppError("bad_kind", 400, "kind must be product, person or prop", kind=kind)
    now = db.now()
    sort = int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) + 1 FROM subjects", default=1))
    subject_id = db.insert("subjects", {
        "name": clean_text(name, MAX_NAME), "kind": kind, "description": clean_block(description, MAX_DESCRIPTION),
        "description_source": "manual", "one_off": bool(one_off), "sort": sort, "created_at": now,
        "updated_at": now,
    })
    publish("subject", subject_id=subject_id)
    return get_subject(subject_id)


def update_subject(subject_id: int, *, name: str | None = None, kind: str | None = None,
                   description: str | None = None, describe_focus: str | None = None,
                   cover_file_id: int | None = None) -> dict:
    row = _row(subject_id)
    values: dict[str, Any] = {}
    if name is not None:
        values["name"] = clean_text(name, MAX_NAME)
    if kind is not None:
        if kind not in KINDS:
            raise AppError("bad_kind", 400, "kind must be product, person or prop", kind=kind)
        values["kind"] = kind
    if description is not None:
        text = clean_block(description, MAX_DESCRIPTION)
        if text != row["description"]:
            # Anything typed by the user is "manual" and is protected from describe-from-photos.
            values["description"] = text
            values["description_source"] = "manual"
    if describe_focus is not None:
        values["describe_focus"] = clean_text(describe_focus, MAX_FOCUS)
    if cover_file_id is not None:
        if cover_file_id and not any(p["file_id"] == cover_file_id for p in _photos(subject_id)):
            raise AppError("bad_cover", 400, "The cover must be one of the subject's photos")
        values["cover_file_id"] = cover_file_id or None
    if values:
        _touch(subject_id, values)
        publish("subject", subject_id=subject_id)
    return get_subject(subject_id)


def promote_subject(subject_id: int) -> dict:
    """One-off -> library. There is no way back (a library subject may be used anywhere)."""
    row = _row(subject_id)
    if row["one_off"]:
        _touch(subject_id, {"one_off": False})
        publish("subject", subject_id=subject_id)
    return get_subject(subject_id)


def delete_subject(subject_id: int) -> None:
    _row(subject_id)
    file_ids = [p["file_id"] for p in _photos(subject_id)]
    with db.tx():
        db.execute("DELETE FROM subject_photos WHERE subject_id = ?", (subject_id,))
        db.delete("subjects", subject_id)
    for fid in file_ids:
        drop_own_file(fid, SOURCE_SUBJECT)
    publish("subject_deleted", subject_id=subject_id)


def reorder_subjects(subject_ids: list[int]) -> None:
    with db.tx():
        for index, subject_id in enumerate(subject_ids):
            db.update("subjects", subject_id, {"sort": index + 1})
    publish("subject_order")


# ── photos ──────────────────────────────────────────────────────────────────


def _check_room(subject_id: int, adding: int = 1) -> None:
    count = db.fetch_value("SELECT COUNT(*) FROM subject_photos WHERE subject_id = ?", (subject_id,), default=0)
    if count + adding > MAX_PHOTOS:
        raise AppError("subject_photo_limit", 400, f"A subject can have up to {MAX_PHOTOS} photos",
                       max=MAX_PHOTOS)


def _insert_photo(subject_id: int, file_id: int, angle: str) -> dict:
    sort = int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) + 1 FROM subject_photos WHERE subject_id = ?",
                              (subject_id,), default=1))
    db.insert("subject_photos", {"subject_id": subject_id, "file_id": file_id,
                                 "angle": clean_text(angle, MAX_ANGLE), "sort": sort, "created_at": db.now()})
    _touch(subject_id)
    publish("subject", subject_id=subject_id)
    return get_subject(subject_id)


def add_photo_upload(subject_id: int, data: bytes, *, filename: str | None = None, angle: str = "") -> dict:
    row = _row(subject_id)
    _check_room(subject_id)
    mime = check_image(data, filename)
    saved = save_upload(data, mime=mime, name=filename, source_type=SOURCE_SUBJECT, source_id=subject_id,
                        title=row["name"] or filename)
    return _insert_photo(subject_id, saved["id"], angle)


def add_photo_from_file(subject_id: int, file_id: int, *, angle: str = "") -> dict:
    """Use a picture that is already stored (media library, chat attachment, generated image)."""
    _row(subject_id)
    _check_room(subject_id)
    row = files.get(file_id)
    if row["mime"] not in IMAGE_MIMES:
        raise AppError("bad_image_type", 400, "Only PNG, JPEG and WebP pictures are supported")
    return _insert_photo(subject_id, file_id, angle)


def update_photo(photo_id: int, *, angle: str | None = None) -> dict:
    photo = _photo_row(photo_id)
    if angle is not None:
        db.update("subject_photos", photo_id, {"angle": clean_text(angle, MAX_ANGLE)})
        _touch(photo["subject_id"])
        publish("subject", subject_id=photo["subject_id"])
    return get_subject(photo["subject_id"])


def delete_photo(photo_id: int) -> dict:
    photo = _photo_row(photo_id)
    subject = _row(photo["subject_id"])
    db.delete("subject_photos", photo_id)
    values = {"cover_file_id": None} if subject["cover_file_id"] == photo["file_id"] else {}
    _touch(subject["id"], values)
    drop_own_file(photo["file_id"], SOURCE_SUBJECT)
    publish("subject", subject_id=subject["id"])
    return get_subject(subject["id"])


def reorder_photos(subject_id: int, photo_ids: list[int]) -> dict:
    _row(subject_id)
    own = {p["id"] for p in _photos(subject_id)}
    unknown = [i for i in photo_ids if i not in own]
    if unknown:
        raise AppError("bad_order", 400, "These photos are not in this subject", ids=unknown)
    rest = [i for i in (p["id"] for p in _photos(subject_id)) if i not in photo_ids]
    with db.tx():
        for index, photo_id in enumerate([*photo_ids, *rest]):
            db.update("subject_photos", photo_id, {"sort": index + 1})
    _touch(subject_id)
    publish("subject", subject_id=subject_id)
    return get_subject(subject_id)


# ── for generation (studio 04, chat 15) ─────────────────────────────────────


def normalize_subject_ids(value: Any, limit: int = MAX_SUBJECTS_PER_REQUEST) -> list[int]:
    """Ids from ints, digit strings or ``{"id": ...}`` dicts; deduplicated, order kept."""
    out: list[int] = []
    for item in value or []:
        raw = item.get("id") if isinstance(item, dict) else item
        try:
            subject_id = int(raw)
        except (TypeError, ValueError):
            continue
        if subject_id > 0 and subject_id not in out:
            out.append(subject_id)
        if len(out) >= limit:
            break
    return out


def subject_images(subject_id: int, limit: int = PHOTOS_SENT) -> list[dict]:
    """The photos that go to the model, in order: ``[{"file_id", "angle", "mime"}]``."""
    rows = db.fetch_all(
        "SELECT p.file_id, p.angle, f.mime FROM subject_photos p JOIN files f ON f.id = p.file_id "
        "WHERE p.subject_id = ? ORDER BY p.sort, p.id LIMIT ?", (subject_id, limit))
    return [{"file_id": r["file_id"], "angle": r["angle"], "mime": r["mime"]} for r in rows]


def describe_subjects(subject_ids: Any) -> list[dict]:
    """Words only (no photos): ``[{"id", "name", "kind", "description"}]`` in the given order.
    Unknown ids and subjects with neither a name nor a description are skipped."""
    out = []
    for subject_id in normalize_subject_ids(subject_ids):
        row = db.get("subjects", subject_id)
        if row is None or not (row["name"] or row["description"]):
            continue
        out.append({"id": row["id"], "name": row["name"], "kind": row["kind"], "description": row["description"]})
    return out


def subject_groups(subject_ids: Any, *, max_photos: int = PHOTOS_SENT, blobs: bool = False) -> list[dict]:
    """What the image model gets per subject, in the given order::

        [{"id", "name", "kind", "description",
          "photos": [{"file_id", "angle", "mime"(, "blob": google.Blob)}]}]

    Subjects without photos are dropped (words alone are ``describe_subjects``).
    Never raises for a missing subject or file: generation must not fail on a stale id.
    """
    from vf.core import google

    out = []
    for subject_id in normalize_subject_ids(subject_ids):
        row = db.get("subjects", subject_id)
        if row is None:
            continue
        photos = []
        for photo in subject_images(subject_id, limit=max_photos):
            if blobs:
                try:
                    photo["blob"] = google.blob_from_file(photo["file_id"])
                except (AppError, OSError):
                    continue
            photos.append(photo)
        if not photos:
            continue
        out.append({"id": row["id"], "name": row["name"], "kind": row["kind"], "description": row["description"],
                    "photos": photos})
    return out


def find_subject_by_name(name: str, *, include_one_off: bool = False) -> dict | None:
    """Library subject with this name (case-insensitive), or None."""
    name = clean_text(name, MAX_NAME)
    if not name:
        return None
    sql = "SELECT * FROM subjects WHERE name = ? COLLATE NOCASE"
    if not include_one_off:
        sql += " AND one_off = 0"
    row = db.fetch_one(sql + " ORDER BY sort, id LIMIT 1", (name,))
    if row is None:  # NOCASE folds ASCII only; compare the rest in Python
        wanted = name.casefold()
        rows = db.fetch_all("SELECT * FROM subjects" + ("" if include_one_off else " WHERE one_off = 0")
                            + " ORDER BY sort, id")
        row = next((r for r in rows if r["name"].casefold() == wanted), None)
    return get_subject(row["id"]) if row else None


_WORD = re.compile(r"\w")


def match_mentions(text: str, *, extra_ids: Any = ()) -> list[dict]:
    """``@Name`` mentions in a chat message: ``[{"id", "name", "start", "end"}]`` in text order.

    Names may contain spaces ("@Red mug"); the longest matching name wins and a
    name must end at a non-word character. Library subjects always count;
    ``extra_ids`` adds one-off subjects attached to the work.
    """
    if not text or "@" not in text:
        return []
    rows = db.fetch_all("SELECT id, name, one_off FROM subjects WHERE name != ''")
    extra = set(normalize_subject_ids(extra_ids))
    candidates = sorted(((r["name"].casefold(), r["id"], r["name"]) for r in rows
                         if not r["one_off"] or r["id"] in extra), key=lambda c: -len(c[0]))
    folded = text.casefold()
    found: list[dict] = []
    pos = folded.find("@")
    while pos != -1:
        next_from = pos + 1
        for name, subject_id, original in candidates:
            end = pos + 1 + len(name)
            if folded[pos + 1:end] == name and (end >= len(text) or not _WORD.match(text[end])):
                found.append({"id": subject_id, "name": original, "start": pos, "end": end})
                next_from = end
                break
        pos = folded.find("@", next_from)
    return found


# ── file usage: a photo of a subject cannot be deleted from the media library ──


@files.usage_provider
def _subject_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT DISTINCT s.id, s.name FROM subject_photos p JOIN subjects s ON s.id = p.subject_id "
        "WHERE p.file_id = ?", (file_id,))
    return [{"type": "subject", "id": r["id"], "title": r["name"] or f"#{r['id']}"} for r in rows]
