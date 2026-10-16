"""Download the work: a ZIP with the picture each frame shows now, in frame order."""

from __future__ import annotations

import io
import re
import zipfile

from vf.core import files
from vf.core.errors import AppError
from vf.modules.studio import works as W

EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


def zip_name(work: dict) -> str:
    return f"{_slug(work['title']) or 'studio'}-{work['id']}.zip"


def build_zip(work_id: int) -> tuple[bytes, str]:
    """``(zip bytes, file name)``. ``nothing_to_export`` (409) when no frame has a picture."""
    work = W.work_row(work_id)
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for frame in W.frames_of(work_id):
            if not frame.get("file_id"):
                continue
            try:
                row = files.get(frame["file_id"])
                data = files.read_bytes(row["id"])
            except (AppError, OSError):
                continue
            zf.writestr(f"{frame['position'] + 1:02d}.{EXT.get(row['mime'], row.get('ext') or 'png')}", data)
            added += 1
    if not added:
        raise AppError("nothing_to_export", 409, "No frame has a picture yet")
    return buf.getvalue(), zip_name(work)
