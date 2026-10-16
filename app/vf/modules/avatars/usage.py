"""Links from the rest of the app into the avatars.

- media library: a picture shown by an avatar (a photo, a candidate, the face,
  a shot) is "used" and cannot be deleted from there; an old face moved to the
  history is not counted, so it may be deleted;
- spend screen: journal refs "avatar" and "avatar_photo" get a title, a link to
  the avatar chat and a thumbnail;
- every minute: pictures and «Describe» messages left behind by a restart or a
  hung request are put in order.
"""

from __future__ import annotations

from vf.core import db, files, scheduler
from vf.modules.avatars import draw, identity
from vf.modules.avatars.common import REF_AVATAR, REF_PHOTO, USAGE_TYPE
from vf.modules.spend import register_ref


def _link(avatar: dict) -> str:
    return f"/chat/{avatar['chat_id']}" if avatar.get("chat_id") else "/chat"


@files.usage_provider
def _avatar_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT a.id, a.name, a.chat_id FROM avatars a WHERE a.face_file_id = :id"
        " OR EXISTS (SELECT 1 FROM avatar_photos p WHERE p.avatar_id = a.id AND p.file_id = :id"
        "            AND p.status != 'archived')"
        " ORDER BY a.id",
        {"id": file_id})
    return [{"type": USAGE_TYPE, "id": r["id"], "title": r["name"] or f"#{r['id']}", "url": _link(r)}
            for r in rows]


def _thumb(file_id: int | None) -> str | None:
    if not file_id or db.get("files", file_id) is None:
        return None
    return files.url(file_id, w=160)


def _avatar_ref(avatar_id: int) -> dict | None:
    row = db.get("avatars", avatar_id)
    if row is None:
        return None
    return {"title": row["name"] or f"#{avatar_id}", "link": _link(row), "thumb_url": _thumb(row.get("face_file_id"))}


def _photo_ref(photo_id: int) -> dict | None:
    row = db.get("avatar_photos", photo_id)
    if row is None:
        return None
    avatar = db.get("avatars", row["avatar_id"]) or {"id": row["avatar_id"], "name": "", "chat_id": None}
    what = row.get("shot_code") or row.get("title") or row["kind"]
    out = {"title": f"{avatar['name'] or '#' + str(avatar['id'])} · {what}", "link": _link(avatar)}
    if row.get("file_id") and db.get("files", row["file_id"]) is not None:
        out["url"] = files.url(row["file_id"])
        out["thumb_url"] = files.url(row["file_id"], w=160)
    return out


register_ref(REF_AVATAR, _avatar_ref)
register_ref(REF_PHOTO, _photo_ref)


@scheduler.every_minute
async def _sweep_avatars() -> None:
    # On the event loop (not in a thread): stopping a hung job touches asyncio tasks.
    draw.sweep()
    identity.settle_all()
