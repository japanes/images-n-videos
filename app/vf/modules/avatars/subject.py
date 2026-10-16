"""A ready avatar as a "person" subject of the brand library (module 08).

That is the whole hook for «pick the avatar as a subject in the studio» and for
``@name`` in any chat: both already work with library subjects, so a ready
avatar is mirrored into one. The mirror is owned by the avatar:

  description  the identity, cut to the subject limit at the end of a sentence
  photos       the face first, then the marked pictures (the same ones a shot sends)
  cover        the face

It exists while the avatar is ready (identity + face + name), not archived and
«use as a subject» is on; otherwise it is removed. Edits made to the mirror on
the brand screen are overwritten by the next change of the avatar.
A failed sync never breaks the avatar action that caused it — it is logged.
"""

from __future__ import annotations

from vf.core import db
from vf.core.errors import AppError
from vf.modules.avatars import compose
from vf.modules.avatars.common import log
from vf.modules.brand import subjects as brand_subjects

KIND = "person"


def description(identity: str) -> str:
    """The identity within the subject limit, cut after the last full sentence that fits."""
    text = (identity or "").strip()
    limit = brand_subjects.MAX_DESCRIPTION
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind(".\n"), head.rfind("\n"))
    return (head[:cut + 1] if cut > limit // 2 else head).strip()


def ready(avatar: dict) -> bool:
    return bool(avatar.get("as_subject") and not avatar.get("archived_at") and avatar.get("face_file_id")
                and (avatar.get("identity") or "").strip() and (avatar.get("name") or "").strip())


def _drop(avatar: dict) -> None:
    subject_id = avatar.get("subject_id")
    if not subject_id:
        return
    try:
        brand_subjects.delete_subject(int(subject_id))
    except AppError:
        pass   # already gone (deleted on the brand screen)
    db.update("avatars", avatar["id"], {"subject_id": None})


def _existing(avatar: dict) -> dict | None:
    subject_id = avatar.get("subject_id")
    if not subject_id:
        return None
    try:
        return brand_subjects.get_subject(int(subject_id))
    except AppError:
        return None


def _sync(avatar: dict) -> int | None:
    if not ready(avatar):
        _drop(avatar)
        return None
    text = description(avatar["identity"])
    photos = compose.shot_photos(avatar)
    subject = _existing(avatar)
    if subject is None:
        subject = brand_subjects.create_subject(avatar["name"], KIND, description=text)
        db.update("avatars", avatar["id"], {"subject_id": subject["id"]})
    else:
        brand_subjects.update_subject(subject["id"], name=avatar["name"], kind=KIND, description=text)
    have = [(p["file_id"], p["angle"] or "") for p in subject["photos"]]
    want = [(p["file_id"], p.get("angle") or "") for p in photos]
    if have != want:
        for p in subject["photos"]:
            brand_subjects.delete_photo(p["id"])
        for file_id, angle in want:
            brand_subjects.add_photo_from_file(subject["id"], file_id, angle=angle)
    if avatar.get("face_file_id") and any(f == avatar["face_file_id"] for f, _ in want):
        brand_subjects.update_subject(subject["id"], cover_file_id=avatar["face_file_id"])
    return subject["id"]


def sync(avatar_id: int) -> int | None:
    """Bring the mirrored subject in line with the avatar. Returns its id (None when there is none)."""
    row = db.get("avatars", avatar_id)
    if row is None:
        return None
    try:
        return _sync(row)
    except AppError as exc:
        log.warning("avatar %s: the subject was not updated: %s %s", avatar_id, exc.code, exc.message)
        return row.get("subject_id")


__all__ = ["description", "ready", "sync"]
