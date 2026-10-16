"""The brand's type specimen: one picture with every font of a kit (factory ``font_sheet``).

For «the model draws the letters itself»: the picture model gets the kit's alphabets as a picture,
because it cannot read a font file. Each block is a small grey line with the font's name, then
its Latin alphabet and its digits. A font whose file does not open is left out — a block named
«Playfair» and drawn in Roboto would lie to the model.

The sheet is local work, no model is called. It is drawn once per set of fonts: the signature
(sha1 of asset id, name, family and file of every font, in order) is the key in
``text_font_sheets``; a renamed, reordered, added or replaced font draws a new sheet and the old
one is removed. The file is a service file (never shown in the media library).
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from vf.core import db, files, google
from vf.core.errors import AppError, NotFound
from vf.modules import library
from vf.modules.text import common as C
from vf.modules.text import fonts as F

ALPHABET = "Aa Bb Cc Dd Ee Ff Gg Hh Ii Jj Kk Ll Mm Nn Oo Pp Qq Rr Ss Tt Uu Vv Ww Xx Yy Zz"
DIGITS = "0 1 2 3 4 5 6 7 8 9  &  !  ?  @  #  %  ( )  “ ”"

SHEET_WIDTH = 1400
MARGIN = 56
LABEL_SIZE = 26
SPECIMEN_SIZE = 54
LABEL_GAP = 14
LINE_GAP = 10
BLOCK_GAP = 40

RULE_COLOR = (229, 231, 235)
LABEL_COLOR = (107, 114, 128)
TEXT_COLOR = (17, 17, 17)
BACKGROUND = (255, 255, 255)

MAX_FONTS = 40  # a kit with a hundred fonts would make a picture no model takes

LAYER_PART = "IMAGE_PART_FONT_SHEET"     # the label sent right before the sheet
LAYER_RULE = "IMAGE_SLIDE_FONT_SHEET"    # the line added to the picture prompt

_lock = threading.Lock()


def signature(fonts: list[dict]) -> str:
    """What the sheet is drawn from; anything that would change a pixel changes it."""
    payload = [[str(f.get("asset_id") or ""), str(f.get("name") or ""), str(f.get("family") or ""),
                str(f.get("file_id") or "")] for f in fonts or []]
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


# --- drawing -------------------------------------------------------------------------------


def _sfnt_bytes(data: bytes) -> bytes | None:
    """A .woff is a TTF/OTF in a wrapper; fontTools takes the wrapper off."""
    try:
        font = TTFont(io.BytesIO(data))
        font.flavor = None
        out = io.BytesIO()
        font.save(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - a file that does not open is a skipped block
        return None


def _face(data: bytes | None, size: int) -> ImageFont.FreeTypeFont | None:
    """The font itself at ``size``, or None — deliberately without a substitute face."""
    if not data:
        return None
    try:
        return ImageFont.truetype(io.BytesIO(data), size=size)
    except OSError:
        pass
    unwrapped = _sfnt_bytes(data)
    if not unwrapped:
        return None
    try:
        return ImageFont.truetype(io.BytesIO(unwrapped), size=size)
    except OSError:
        return None


def _face_style(face: ImageFont.FreeTypeFont) -> str:
    try:
        _, style = face.getname()
    except (AttributeError, OSError):
        return ""
    style = (style or "").strip()
    return "" if style.lower() in ("", "regular", "book", "normal") else style


def _label_for(name: str, face: ImageFont.FreeTypeFont) -> str:
    style = _face_style(face)
    if style and style.lower() not in (name or "").lower():
        return f"{name} — {style}"
    return name


def _wrap(text: str, face: ImageFont.FreeTypeFont, width: int, measure) -> list[str]:
    """Greedy wrap on spaces; the alphabet is pairs, so a break never splits «Aa»."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if not word:
            continue
        candidate = f"{current} {word}".strip()
        if current and measure(candidate, face) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_sheet(rows: list[dict]) -> bytes:
    """``rows``: ``{name, bytes}`` in order. Returns PNG bytes, or b"" when nothing was drawable."""
    return _render(rows)[0]


def _render(rows: list[dict]) -> tuple[bytes, int]:
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def measure(text: str, face: ImageFont.FreeTypeFont) -> float:
        return scratch.textlength(text, font=face)

    label_face = F.truetype(F.REGULAR, LABEL_SIZE)
    content_width = SHEET_WIDTH - 2 * MARGIN
    blocks: list[dict] = []
    for row in (rows or [])[:MAX_FONTS]:
        face = _face(row.get("bytes"), SPECIMEN_SIZE)
        if face is None:
            C.log.info("text: font sheet skips «%s» — its file does not open", row.get("name"))
            continue
        lines = _wrap(ALPHABET, face, content_width, measure) + [DIGITS]
        blocks.append({"label": _label_for(str(row.get("name") or ""), face), "face": face, "lines": lines})
    if not blocks:
        return b"", 0
    label_height = LABEL_SIZE + 8
    line_height = int(SPECIMEN_SIZE * 1.28)
    height = MARGIN
    for i, block in enumerate(blocks):
        height += label_height + LABEL_GAP
        height += line_height * len(block["lines"]) + LINE_GAP * (len(block["lines"]) - 1)
        if i < len(blocks) - 1:
            height += BLOCK_GAP
    height += MARGIN
    image = Image.new("RGB", (SHEET_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    y = MARGIN
    for i, block in enumerate(blocks):
        draw.text((MARGIN, y), block["label"], font=label_face, fill=LABEL_COLOR)
        y += label_height + LABEL_GAP
        for j, line in enumerate(block["lines"]):
            draw.text((MARGIN, y), line, font=block["face"], fill=TEXT_COLOR)
            y += line_height
            if j < len(block["lines"]) - 1:
                y += LINE_GAP
        if i < len(blocks) - 1:
            rule = y + BLOCK_GAP // 2
            draw.line([(MARGIN, rule), (SHEET_WIDTH - MARGIN, rule)], fill=RULE_COLOR, width=1)
            y += BLOCK_GAP
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), len(blocks)


# --- storage -------------------------------------------------------------------------------


def _font_bytes(font: dict) -> bytes | None:
    """The font's own file, read as it is (``F.font_path`` refuses files that do not open)."""
    if not font.get("file_id"):
        return None
    try:
        row = files.get(int(font["file_id"]))
        return Path(files.path_of(row)).read_bytes()
    except (AppError, OSError, TypeError, ValueError):
        return None


def _drop(rows: list[dict], keep: int | None = None) -> None:
    for row in rows:
        if keep is not None and row["id"] == keep:
            continue
        db.delete("text_font_sheets", row["id"])
        if row.get("file_id"):
            try:
                files.delete(row["file_id"], force=True)
            except AppError as exc:  # a leftover file is not a failure
                C.log.warning("text: old font sheet %s was not removed (%s)", row["file_id"], exc.code)


def public(row: dict | None, fonts: int, rebuilt: bool) -> dict:
    file_id = row.get("file_id") if row else None
    return {"file_id": file_id, "url": files.url(file_id) if file_id else None, "fonts": fonts,
            "drawn": row.get("fonts", 0) if row else 0, "signature": row.get("signature") if row else None,
            "rebuilt": rebuilt}


def ensure_sheet(kit_id: Any, *, force: bool = False) -> dict:
    """The kit's sheet, drawn now when its fonts changed since the last one.

    → ``{file_id, url, fonts, drawn, signature, rebuilt}``; ``file_id`` None = the kit has no font
    with a file that opens (an old sheet is removed then)."""
    try:
        kit_id = int(kit_id)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "A brand kit id is expected") from None
    kit = db.get("brand_kits", kit_id)
    if kit is None:
        raise NotFound("brand_kit", id=kit_id)
    with _lock:
        fonts = [f for f in F.kit_fonts(kit_id) if f.get("file_id")][:MAX_FONTS]
        existing = db.fetch_all("SELECT * FROM text_font_sheets WHERE kit_id = ? ORDER BY id DESC", (kit_id,))
        if not fonts:
            _drop(existing)
            return public(None, 0, bool(existing))
        sign = signature(fonts)
        if not force:
            for row in existing:
                if row["signature"] == sign and row.get("file_id"):
                    _drop(existing, keep=row["id"])
                    return public(row, len(fonts), False)
        png, drawn = _render([{"name": f.get("name") or f.get("family") or "", "bytes": _font_bytes(f)}
                              for f in fonts])
        if not png:
            C.log.warning("text: kit %s has fonts but none of them opens; no sheet", kit_id)
            _drop(existing)
            return public(None, len(fonts), bool(existing))
        _drop(existing)
        saved = files.save_bytes(png, mime="image/png", name="font-sheet.png", origin="generated", service=True,
                                 title=f"Font sheet · {kit.get('name') or kit_id}", source_type=C.SOURCE_SHEET,
                                 source_id=kit_id, meta={"signature": sign, "fonts": drawn})
        row_id = db.insert("text_font_sheets", {"signature": sign, "kit_id": kit_id, "file_id": saved["id"],
                                                "fonts": drawn, "created_at": db.now()}, or_replace=True)
        return public(db.get("text_font_sheets", row_id), len(fonts), True)


def lettering_rule() -> str:
    """The line the picture prompt gets when the sheet goes along («letter it in these faces»)."""
    return library.render_layer(LAYER_RULE, {}).strip()


def studio_parts(kit_id: Any) -> list:
    """For the studio's «the model draws the letters» mode: ``[label + ":", Blob]`` to put among the
    pictures of the request, or ``[]`` when the kit has no drawable font. The prompt then adds
    :func:`lettering_rule`. (The studio does not call it yet — see the module's task log.)"""
    sheet = ensure_sheet(kit_id)
    if not sheet["file_id"]:
        return []
    label = library.render_layer(LAYER_PART, {}).strip()
    return [label + ":", google.blob_from_file(sheet["file_id"])]


__all__ = ["ensure_sheet", "lettering_rule", "render_sheet", "signature", "studio_parts"]
