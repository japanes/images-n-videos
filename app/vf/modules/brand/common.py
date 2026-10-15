"""Small helpers shared by kits and subjects: upload checks, file cleanup, events."""

from __future__ import annotations

import io
import logging

from vf.core import events, files
from vf.core.errors import AppError

log = logging.getLogger("vf.brand")

# Pictures the Google image models accept as input.
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_FONT_BYTES = 20 * 1024 * 1024

SOURCE_ASSET = "brand_asset"
SOURCE_SUBJECT = "brand_subject"


def clean_text(value: str | None, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def clean_block(value: str | None, limit: int) -> str:
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


def save_upload(data: bytes, *, mime: str, name: str | None, source_type: str, source_id: int,
                title: str | None = None) -> dict:
    return files.save_bytes(data, mime=mime, name=name, origin="upload", title=title or name,
                            source_type=source_type, source_id=source_id)


def drop_own_file(file_id: int | None, source_type: str) -> None:
    """Delete a file this module uploaded, once nothing uses it any more.
    Files picked from elsewhere (media library, chat attachments) are left alone."""
    if not file_id:
        return
    try:
        row = files.get(file_id)
    except AppError:
        return
    if row.get("source_type") != source_type:
        return
    try:
        files.delete(file_id)
    except AppError as exc:
        if exc.code != "file_in_use":
            raise
        log.info("file %s is still used elsewhere, kept", file_id)


def publish(what: str, **data) -> None:
    events.publish("brand.updated", {"what": what, **data})
