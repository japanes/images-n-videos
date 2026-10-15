"""Files on the data volume: ``files/YYYY/MM/<uuid>.<ext>`` plus a ``files`` row.

Other code never builds paths itself: it calls ``save_bytes`` / ``save_file`` /
``allocate`` + ``register`` and keeps the file id. Modules that reference files
register a usage provider so the media library can say "where is it used" and
refuse to delete a file that is still needed::

    @files.usage_provider
    def _usages(file_id: int) -> list[dict]:
        return [{"type": "avatar", "id": 3, "title": "Anna"}]
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vf.core import db, events
from vf.core.config import get_config
from vf.core.errors import AppError, NotFound

KIND_BY_MIME_PREFIX = {"image/": "image", "video/": "video", "audio/": "audio", "font/": "font"}
EXT_BY_MIME = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
    "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/aac": "aac",
    "audio/ogg": "ogg", "font/ttf": "ttf", "font/otf": "otf", "font/woff2": "woff2",
    "application/json": "json", "text/plain": "txt",
}
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("audio/mp4", ".m4a")

_usage_providers: list[Callable[[int], list[dict]]] = []


def usage_provider(func: Callable[[int], list[dict]]) -> Callable[[int], list[dict]]:
    _usage_providers.append(func)
    return func


def data_dir() -> Path:
    return get_config().data_dir


def abs_path(rel: str | Path) -> Path:
    """Absolute path of a data-relative path; refuses anything outside the volume."""
    root = data_dir().resolve()
    p = (root / str(rel)).resolve()
    if p != root and root not in p.parents:
        raise AppError("bad_path", 400, path=str(rel))
    return p


def rel_path(p: Path) -> str:
    return str(p.resolve().relative_to(data_dir().resolve()))


def kind_of(mime: str | None) -> str:
    for prefix, kind in KIND_BY_MIME_PREFIX.items():
        if mime and mime.startswith(prefix):
            return kind
    return "other"


def guess_mime(name: str | None, data: bytes | None = None) -> str:
    if data:
        sniffed = sniff_mime(data)
        if sniffed:
            return sniffed
    if name:
        mime, _ = mimetypes.guess_type(name)
        if mime:
            return mime
    return "application/octet-stream"


def sniff_mime(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in (b"M4A ", b"M4B "):
            return "audio/mp4"
        return "video/mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:4] == b"OggS":
        return "audio/ogg"
    return None


def allocate(ext: str, *, under: str = "files") -> tuple[str, Path]:
    """A fresh data-relative path (and its absolute twin) for a new file."""
    ext = ext.lstrip(".").lower() or "bin"
    stamp = datetime.now(UTC)
    rel = f"{under}/{stamp:%Y}/{stamp:%m}/{uuid.uuid4().hex}.{ext}"
    p = abs_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    return rel, p


def tmp_path(ext: str) -> tuple[str, Path]:
    rel = f"cache/tmp/{uuid.uuid4().hex}.{ext.lstrip('.')}"
    p = abs_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    return rel, p


def _image_size(data_or_path: bytes | Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        src = io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else data_or_path
        with Image.open(src) as im:
            return im.size
    except Exception:
        return None, None


def register(rel: str, *, mime: str | None = None, origin: str = "generated", service: bool = False,
             title: str | None = None, original_name: str | None = None, source_type: str | None = None,
             source_id: int | None = None, width: int | None = None, height: int | None = None,
             duration: float | None = None, meta: dict | None = None, sha256: str | None = None) -> dict:
    """Create the row for a file that already sits at ``rel`` on the volume."""
    p = abs_path(rel)
    if not p.is_file():
        raise NotFound("file", path=rel)
    if mime is None:
        with p.open("rb") as fh:
            mime = guess_mime(p.name, fh.read(32))
    kind = kind_of(mime)
    if kind == "image" and (width is None or height is None):
        width, height = _image_size(p)
    file_id = db.insert("files", {
        "created_at": db.now(), "kind": kind, "mime": mime, "ext": p.suffix.lstrip(".").lower(),
        "path": rel, "size_bytes": p.stat().st_size, "width": width, "height": height,
        "duration": duration, "sha256": sha256, "origin": origin, "is_service": service,
        "title": title, "original_name": original_name, "source_type": source_type,
        "source_id": source_id, "meta_json": meta or {},
    })
    row = get(file_id)
    events.publish("file.created", public(row))
    return row


def save_bytes(data: bytes, *, mime: str | None = None, name: str | None = None, **kwargs: Any) -> dict:
    mime = mime or guess_mime(name, data)
    ext = EXT_BY_MIME.get(mime) or (Path(name).suffix.lstrip(".") if name else "bin")
    rel, p = allocate(ext)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(p)
    kwargs.setdefault("sha256", hashlib.sha256(data).hexdigest())
    if kind_of(mime) == "image" and ("width" not in kwargs or "height" not in kwargs):
        kwargs["width"], kwargs["height"] = _image_size(data)
    return register(rel, mime=mime, original_name=kwargs.pop("original_name", name), **kwargs)


def save_file(src: Path, *, mime: str | None = None, name: str | None = None, move: bool = True,
              **kwargs: Any) -> dict:
    """Store a file that already exists on disk (an upload spool, a render output)."""
    if mime is None:
        with src.open("rb") as fh:
            mime = guess_mime(name or src.name, fh.read(32))
    ext = EXT_BY_MIME.get(mime) or (Path(name or src.name).suffix.lstrip(".") or "bin")
    rel, p = allocate(ext)
    if move:
        shutil.move(str(src), str(p))
    else:
        shutil.copyfile(src, p)
    return register(rel, mime=mime, original_name=kwargs.pop("original_name", name), **kwargs)


def get(file_id: int) -> dict:
    row = db.get("files", file_id)
    if row is None:
        raise NotFound("file", id=file_id)
    return row


def path_of(file_id_or_row: int | dict) -> Path:
    row = file_id_or_row if isinstance(file_id_or_row, dict) else get(file_id_or_row)
    return abs_path(row["path"])


def read_bytes(file_id: int) -> bytes:
    return path_of(file_id).read_bytes()


def url(file_id: int | None, **params: Any) -> str | None:
    if not file_id:
        return None
    query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return f"/files/{file_id}" + (f"?{query}" if query else "")


def public(row: dict) -> dict:
    """What the browser gets about a file."""
    return {
        "id": row["id"], "kind": row["kind"], "mime": row["mime"], "url": url(row["id"]),
        "thumb_url": url(row["id"], w=480) if row["kind"] == "image" else (
            f"/files/{row['id']}/poster" if row.get("poster_path") else None),
        "preview_url": f"/files/{row['id']}/preview" if row.get("preview_path") else None,
        "width": row.get("width"), "height": row.get("height"), "duration": row.get("duration"),
        "size_bytes": row.get("size_bytes"), "title": row.get("title"),
        "original_name": row.get("original_name"), "origin": row.get("origin"),
        "is_service": bool(row.get("is_service")), "source_type": row.get("source_type"),
        "source_id": row.get("source_id"), "created_at": row.get("created_at"),
    }


def update(file_id: int, values: dict) -> dict:
    db.update("files", file_id, values)
    row = get(file_id)
    events.publish("file.updated", public(row))
    return row


def usages(file_id: int) -> list[dict]:
    out: list[dict] = []
    for provider in _usage_providers:
        out.extend(provider(file_id) or [])
    return out


def delete(file_id: int, *, force: bool = False) -> None:
    row = get(file_id)
    if not force:
        used = usages(file_id)
        if used:
            raise AppError("file_in_use", 409, usages=used)
    for key in ("path", "poster_path", "preview_path"):
        if row.get(key):
            try:
                abs_path(row[key]).unlink(missing_ok=True)
            except AppError:
                pass
    thumbs = data_dir() / "cache" / "thumbs" / str(file_id)
    shutil.rmtree(thumbs, ignore_errors=True)
    db.delete("files", file_id)
    events.publish("file.deleted", {"id": file_id})
