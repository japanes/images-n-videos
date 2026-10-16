"""Download the pack: one ZIP with the picture every slot shows now, in pack order.

Slots still being drawn or empty are left out, so a half-finished pack downloads
as what is finished. Nothing here costs money.
"""

from __future__ import annotations

import io
import re
import zipfile

from vf.core import files
from vf.core.errors import AppError
from vf.modules.avatars import store

EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


def zip_name(avatar: dict) -> str:
    return f"{_slug(avatar['name']) or 'avatar'}-{avatar['id']}.zip"


def build_zip(avatar_id: int) -> tuple[bytes, str]:
    """``(zip bytes, file name)``. ``nothing_to_export`` (409) when no slot has a picture."""
    avatar = store.avatar_row(avatar_id)
    folder = _slug(avatar["name"]) or f"avatar-{avatar['id']}"
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for index, slot in enumerate(store.slots_of(avatar["id"]), start=1):
            if not slot.get("file_id"):
                continue
            try:
                row = files.get(slot["file_id"])
                data = files.read_bytes(row["id"])
            except (AppError, OSError):
                continue   # one unreadable file should not cost the other pictures
            label = "-".join(x for x in (slot["shot_code"].lower().replace("_", ""), _slug(slot.get("title") or ""))
                             if x)
            zf.writestr(f"{folder}/{index:02d}-{label}.{EXT.get(row['mime'], row.get('ext') or 'png')}", data)
            added += 1
    if not added:
        raise AppError("nothing_to_export", 409, "No slot has a picture yet")
    return buf.getvalue(), zip_name(avatar)


__all__ = ["build_zip", "zip_name"]
