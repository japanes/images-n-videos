"""Constants and small helpers shared by the studio files."""

from __future__ import annotations

import io
import logging
from typing import Any

from vf.core import events, files
from vf.core.errors import AppError

log = logging.getLogger("vf.studio")

# Pictures the Google image models accept as input.
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")
MAX_IMAGE_BYTES = 40 * 1024 * 1024

ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
TEXT_MODES = ("none", "overlay", "model")
TEXT_ROLES = ("headline", "body", "accent")
SOURCES = ("generated", "upload", "library", "avatar", "video_frame", "editor")
FRAME_STATUSES = ("empty", "queued", "drawing", "done", "error")
BUSY = ("queued", "drawing")

MAX_FRAMES = 10
MAX_VERSIONS = 10
MAX_TITLE = 120
MAX_BRIEF = 4000
MAX_EDIT = 2000
MAX_FEEDBACK = 2000
MAX_FOCUS = 300
MAX_WORDS = 600          # one text block
MAX_TEXT_BLOCKS = 6
MAX_PICKED = 14          # references / attachments per work or frame (Gemini takes up to 14 pictures)
MAX_OBJECTS = 24
STUCK_MINUTES = 15

SOURCE_UPLOAD = "studio_upload"   # files.source_type of pictures uploaded into the studio
SOURCE_FRAME = "studio_frame"     # files.source_type of generated frames

PURPOSE_FRAME = "frame"
PURPOSE_EDIT = "frame_edit"
PURPOSE_OBJECTS = "regions"


def clean_text(value: Any, limit: int) -> str:
    """One line: collapses whitespace."""
    return " ".join(str(value or "").split())[:limit]


def clean_block(value: Any, limit: int) -> str:
    """Multi-line text: trims, keeps line breaks."""
    return str(value or "").strip()[:limit]


def check_image(data: bytes, name: str | None) -> str:
    """Mime of an uploaded picture, or a clear error."""
    if not data:
        raise AppError("empty_file", 400, "The file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=MAX_IMAGE_BYTES // 1024 // 1024)
    mime = files.sniff_mime(data[:32])
    if mime not in IMAGE_MIMES:
        raise AppError("bad_image_type", 400, "Only PNG, JPEG and WebP pictures are supported", name=name)
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as exc:  # noqa: BLE001
        raise AppError("bad_image_type", 400, "The picture could not be read", name=name) from exc
    return mime


def image_file(file_id: Any) -> dict:
    """A stored picture by id, or ``bad_file`` (400)."""
    try:
        row = files.get(int(file_id))
    except (TypeError, ValueError, AppError):
        raise AppError("bad_file", 400, "The file is gone or is not a picture", file_id=file_id) from None
    if row["kind"] != "image" or row["mime"] not in IMAGE_MIMES:
        raise AppError("bad_file", 400, "The file is gone or is not a picture", file_id=file_id)
    return row


def file_ids(value: Any, limit: int = MAX_PICKED) -> list[int]:
    """Picture ids from ints, digit strings or ``{"id"}`` / ``{"file_id"}`` dicts.
    Deduplicated, order kept; every id must be an existing picture."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "A list of pictures is expected")
    out: list[int] = []
    for item in value:
        raw = item.get("file_id", item.get("id")) if isinstance(item, dict) else item
        row = image_file(raw)
        if row["id"] not in out:
            out.append(row["id"])
    if len(out) > limit:
        raise AppError("too_many_pictures", 400, "Too many pictures", max=limit)
    return out


def file_brief(file_id: int | None) -> dict | None:
    """Small file card for the browser: id, urls and size; None when the file is gone."""
    if not file_id:
        return None
    try:
        row = files.get(file_id)
    except AppError:
        return None
    return {"id": row["id"], "url": files.url(row["id"]), "thumb_url": files.url(row["id"], w=480),
            "width": row.get("width"), "height": row.get("height"), "mime": row["mime"],
            "title": row.get("title") or row.get("original_name")}


def file_sha(file_id: int) -> str:
    """sha256 of a stored file (computed and saved when the row has none)."""
    import hashlib

    row = files.get(file_id)
    if row.get("sha256"):
        return row["sha256"]
    sha = hashlib.sha256(files.read_bytes(file_id)).hexdigest()
    files.update(file_id, {"sha256": sha})
    return sha


def publish(what: str, **data: Any) -> None:
    events.publish("studio.updated", {"what": what, **data})
