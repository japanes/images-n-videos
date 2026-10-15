"""Uploads from the computer: one endpoint for every screen that takes a file.

The multipart body is parsed while it streams in. The file part goes straight
to ``cache/tmp`` on the data volume (no system temp dir, no full copy in
memory) and is moved into ``files/`` with one rename. The real type comes from
the first bytes of the file, never from its name or the browser's
Content-Type. Each kind has its own size limit (settings ``media.max_*_mb``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import ClientDisconnect, Request

from vf.core import files, settings
from vf.core.errors import AppError

log = logging.getLogger("vf.media.upload")

MB = 1024 * 1024
SNIFF_BYTES = 512
MAX_FIELD_BYTES = 64 * 1024
MAX_PARTS = 16
MAX_NAME = 255
MAX_TITLE = 200
MULTIPART_OVERHEAD = 1 * MB

LIBRARY_KINDS = ("image", "video", "audio")
UPLOAD_KINDS = (*LIBRARY_KINDS, "font")

# The whitelist: real type (from bytes) -> extension on disk.
ALLOWED: dict[str, str] = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
    "audio/mpeg": "mp3", "audio/wav": "wav", "audio/mp4": "m4a", "audio/aac": "aac",
    "audio/ogg": "ogg", "audio/flac": "flac",
    "font/ttf": "ttf", "font/otf": "otf", "font/woff": "woff", "font/woff2": "woff2",
}

# ISO-BMFF brands that are still images (HEIC/AVIF): not supported.
_IMAGE_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"}
# Old QuickTime files may start with one of these atoms instead of ``ftyp``.
_QT_ATOMS = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}

settings.define("media.max_image_mb", 25, group="media", kind="int", min=1, max=500)
settings.define("media.max_video_mb", 300, group="media", kind="int", min=1, max=4096)
settings.define("media.max_audio_mb", 100, group="media", kind="int", min=1, max=2048)

_LIMIT_KEYS = {"image": "media.max_image_mb", "video": "media.max_video_mb",
               "audio": "media.max_audio_mb", "font": "media.max_image_mb"}


def limit_mb(kind: str) -> int:
    return int(settings.get(_LIMIT_KEYS[kind]))


def limits() -> dict:
    """What the browser needs to check a file before sending it."""
    return {
        "max_mb": {kind: limit_mb(kind) for kind in UPLOAD_KINDS},
        "types": {kind: sorted(m for m in ALLOWED if files.kind_of(m) == kind) for kind in UPLOAD_KINDS},
        "default_kinds": list(LIBRARY_KINDS),
    }


def sniff(head: bytes) -> str | None:
    """The real type of a file from its first bytes; ``None`` when it is not on the whitelist."""
    box = head[4:8]
    if box == b"ftyp":
        return None if head[8:12] in _IMAGE_BRANDS else files.sniff_mime(head)
    if box in _QT_ATOMS:
        return "video/quicktime"
    if head[:4] == b"fLaC":
        return "audio/flac"
    if head[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "audio/aac"
    if head[:2] == b"\xff\xfa":
        return "audio/mpeg"
    if head[:4] in (b"\x00\x01\x00\x00", b"true"):
        return "font/ttf"
    if head[:4] == b"OTTO":
        return "font/otf"
    if head[:4] == b"wOFF":
        return "font/woff"
    if head[:4] == b"wOF2":
        return "font/woff2"
    mime = files.sniff_mime(head)
    if mime == "video/webm" and b"webm" not in head:
        return None  # Matroska (.mkv) shares the header with WebM; browsers do not play it reliably
    return mime if mime in ALLOWED else None


def parse_kinds(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """``"image,video"`` -> ``("image", "video")``. Empty means the library kinds."""
    if value is None or value == "":
        return LIBRARY_KINDS
    items = value.split(",") if isinstance(value, str) else list(value)
    kinds = tuple(dict.fromkeys(k.strip().lower() for k in items if k and k.strip()))
    bad = [k for k in kinds if k not in UPLOAD_KINDS]
    if bad or not kinds:
        raise AppError("bad_request", 400, "unknown file kind", kinds=bad)
    return kinds


def clean_name(raw: str | None) -> str | None:
    """The file name as the person had it, without folders and control characters."""
    if not raw:
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if len(name) > MAX_NAME:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: MAX_NAME - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else name[:MAX_NAME]
    return name or None


def clean_title(raw: str | None) -> str | None:
    if raw is None:
        return None
    title = re.sub(r"[\x00-\x1f\x7f]", " ", raw).strip()
    return title[:MAX_TITLE] or None


def too_large(kind: str | None, mb: int) -> AppError:
    return AppError("file_too_large", 413, f"the file is larger than {mb} MB", kind=kind, max_mb=mb)


@dataclass
class Received:
    """A file that arrived and is waiting in ``cache/tmp``."""

    spool: Path
    size: int
    sha256: str
    mime: str
    kind: str
    original_name: str | None
    fields: dict[str, str] = field(default_factory=dict)

    def discard(self) -> None:
        self.spool.unlink(missing_ok=True)


class _Receiver:
    """Callbacks for ``MultipartParser``: one file part to disk, small text fields to memory."""

    def __init__(self, kinds: tuple[str, ...]):
        self.kinds = kinds
        self.hard_cap = max(limit_mb(k) for k in kinds) * MB
        self.limit = self.hard_cap
        self.fields: dict[str, str] = {}
        self.file_name: str | None = None
        self.file_seen = False
        self.spool: Path | None = None
        self.fh: IO[bytes] | None = None
        self.size = 0
        self.head = bytearray()
        self.mime: str | None = None
        self.kind: str | None = None
        self.sha = hashlib.sha256()
        self.parts = 0
        self._hfield = bytearray()
        self._hvalue = bytearray()
        self._headers: dict[str, str] = {}
        self._target: str | None = None  # "file" | "field" | None (ignored part)
        self._field_name = ""
        self._buf = bytearray()

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self._part_begin, "on_header_field": self._header_field,
            "on_header_value": self._header_value, "on_header_end": self._header_end,
            "on_headers_finished": self._headers_finished, "on_part_data": self._part_data,
            "on_part_end": self._part_end,
        }

    def _part_begin(self) -> None:
        self.parts += 1
        if self.parts > MAX_PARTS:
            raise AppError("bad_request", 400, "too many form fields")
        self._headers = {}
        self._target = None
        self._buf = bytearray()

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._hfield += data[start:end]

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._hvalue += data[start:end]

    def _header_end(self) -> None:
        self._headers[self._hfield.decode("latin-1").strip().lower()] = self._hvalue.decode("latin-1")
        self._hfield = bytearray()
        self._hvalue = bytearray()

    def _headers_finished(self) -> None:
        _disp, opts = parse_options_header(self._headers.get("content-disposition"))
        name = opts.get(b"name", b"").decode("utf-8", "replace")
        filename = opts.get(b"filename")
        if filename is not None:
            if name != "file":
                return  # a file under another name is ignored
            if self.file_seen:
                raise AppError("bad_request", 400, "one file per request")
            self.file_seen = True
            self.file_name = clean_name(filename.decode("utf-8", "replace"))
            _rel, self.spool = files.tmp_path("part")
            self.fh = self.spool.open("wb")
            self._target = "file"
        elif name:
            self._target = "field"
            self._field_name = name

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if self._target == "file":
            self._write(data[start:end])
        elif self._target == "field":
            self._buf += data[start:end]
            if len(self._buf) > MAX_FIELD_BYTES:
                raise AppError("bad_request", 400, "form field is too long", field=self._field_name)

    def _part_end(self) -> None:
        if self._target == "field":
            self.fields[self._field_name] = self._buf.decode("utf-8", "replace")
        elif self._target == "file" and self.mime is None and self.size:
            self._classify()
        self._target = None

    def _write(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.size += len(chunk)
        if self.mime is None:
            self.head += chunk[: SNIFF_BYTES - len(self.head)]
            if len(self.head) >= SNIFF_BYTES:
                self._classify()
        if self.size > self.limit:
            raise too_large(self.kind, self.limit // MB)
        self.sha.update(chunk)
        assert self.fh is not None
        self.fh.write(chunk)

    def _classify(self) -> None:
        mime = sniff(bytes(self.head))
        kind = files.kind_of(mime) if mime else None
        if mime is None or kind not in self.kinds:
            raise AppError("unsupported_type", 415, "this file type is not supported here",
                           kinds=list(self.kinds), detected=mime)
        self.mime, self.kind = mime, kind
        self.limit = limit_mb(kind) * MB

    def close(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None

    def discard(self) -> None:
        self.close()
        if self.spool is not None:
            self.spool.unlink(missing_ok=True)


async def receive(request: Request, kinds: tuple[str, ...] = LIBRARY_KINDS) -> Received:
    """Read a ``multipart/form-data`` body with one ``file`` part (plus small text fields)."""
    ctype, opts = parse_options_header(request.headers.get("content-type"))
    boundary = opts.get(b"boundary")
    if ctype != b"multipart/form-data" or not boundary:
        raise AppError("bad_request", 400, "send the file as multipart/form-data in the field 'file'")
    rx = _Receiver(kinds)
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > rx.hard_cap + MULTIPART_OVERHEAD:
        raise too_large(kinds[0] if len(kinds) == 1 else None, rx.hard_cap // MB)
    parser = MultipartParser(boundary, callbacks=rx.callbacks())
    try:
        async for chunk in request.stream():
            if chunk:
                parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        rx.discard()
        raise AppError("bad_request", 400, "the upload is broken") from exc
    except ClientDisconnect as exc:
        rx.discard()
        raise AppError("aborted", 400, "the upload was interrupted") from exc
    except BaseException:
        rx.discard()
        raise
    rx.close()
    if not rx.file_seen or rx.size == 0 or rx.spool is None:
        rx.discard()
        raise AppError("upload_empty", 400, "no file or the file is empty")
    if rx.mime is None:
        try:
            rx._classify()
        except AppError:
            rx.discard()
            raise
    assert rx.mime and rx.kind
    return Received(rx.spool, rx.size, rx.sha.hexdigest(), rx.mime, rx.kind, rx.file_name, rx.fields)


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.size
    except Exception as exc:  # noqa: BLE001 - any decoder error means "not a readable image"
        raise AppError("unsupported_type", 415, "the image cannot be read", detected="broken image") from exc


async def store(rx: Received, *, title: str | None = None) -> dict:
    """Move a received file into ``files/`` and create its row (``origin = upload``)."""
    try:
        width = height = None
        if rx.kind == "image":
            width, height = await asyncio.to_thread(_image_size, rx.spool)
        rel, dest = files.allocate(ALLOWED[rx.mime])
        await asyncio.to_thread(shutil.move, str(rx.spool), str(dest))
    except BaseException:
        rx.discard()
        raise
    try:
        return files.register(rel, mime=rx.mime, origin="upload", title=clean_title(title),
                              original_name=rx.original_name, sha256=rx.sha256, width=width, height=height)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
