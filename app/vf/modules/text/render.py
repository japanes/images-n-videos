"""Pillow renderer: the layers of a design drawn over the background.

Ported from factory ``services/text_overlay_service._pillow_overlay_blocks``: the
words wrap inside their box, shrink by 3 px until they fit (a word wider than the
box keeps shrinking down to 6 px), what still does not fit is cut at the box edge;
the plate behind the words is a soft band (dark under light words, light under
dark ones), the shadow sits 2 px down and right.

New here: every character is drawn by the first font that has it — the brand
font, then the bundled Roboto (Latin + Cyrillic). So a Latin-only brand font
never leaves boxes («tofu») in a Cyrillic line; the report names the characters
that went to Roboto and the ones no font has (those are left out, not drawn as boxes).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from vf.core import files
from vf.core.errors import AppError
from vf.modules.text import common as C
from vf.modules.text import fonts as F

ABS_MIN_FONT = 6
SCRIM_BLUR = 8


@dataclass
class Report:
    width: int = 0
    height: int = 0
    fallback_chars: set[str] = field(default_factory=set)   # drawn with Roboto, the brand font lacks them
    missing_chars: set[str] = field(default_factory=set)    # no font has them: left out
    clipped: list[str] = field(default_factory=list)        # layers whose words did not all fit
    missing_files: list[str] = field(default_factory=list)  # layers whose font or logo file is gone

    def public(self) -> dict:
        return {"width": self.width, "height": self.height,
                "fallback_chars": "".join(sorted(self.fallback_chars)),
                "missing_chars": "".join(sorted(self.missing_chars)),
                "clipped": self.clipped, "missing_files": self.missing_files}


class Face:
    """The fonts of one text layer at one size: the brand font (if any) and Roboto."""

    def __init__(self, primary: Path | None, bold: bool, size: int):
        self.size = size
        self.bold = bold
        self.primary = F.truetype(primary, size) if primary else None
        self.primary_cov = F.coverage(primary) if primary else frozenset()
        fallback = F.fallback_path(bold)
        self.fallback = F.truetype(fallback, size)
        self.fallback_cov = F.coverage(fallback)
        # Bold of a brand font: its file is one weight, so the strokes are thickened.
        self.stroke = max(1, round(size * 0.025)) if (bold and self.primary is not None) else 0
        main = self.primary or self.fallback
        self.ascent, self.descent = main.getmetrics()

    def runs(self, text: str, report: Report | None = None) -> list[tuple[str, Any, int]]:
        """``[(chars, font, stroke)]``: neighbouring characters of one font joined."""
        out: list[tuple[str, Any, int]] = []
        for ch in text:
            code = ord(ch)
            if self.primary is not None and (code in self.primary_cov or ch == " "):
                font, stroke = self.primary, self.stroke
            elif code in self.fallback_cov or ch == " ":
                font, stroke = self.fallback, 0
                if report is not None and self.primary is not None:
                    report.fallback_chars.add(ch)
            else:
                if report is not None and not ch.isspace():
                    report.missing_chars.add(ch)
                continue
            if out and out[-1][1] is font:
                out[-1] = (out[-1][0] + ch, font, stroke)
            else:
                out.append((ch, font, stroke))
        return out

    def width(self, text: str) -> float:
        return sum(font.getlength(chars) + 2 * stroke for chars, font, stroke in self.runs(text))


def wrap(text: str, face: Face, max_width: float) -> list[str]:
    """Greedy word wrap by measured width; the person's own line breaks stay."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}" if current else word
            if not current or face.width(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _px_box(layer: dict, width: int, height: int) -> tuple[int, int, int, int]:
    x = int(round(layer["x"] * width))
    y = int(round(layer["y"] * height))
    w = max(16, min(int(round(layer["w"] * width)), width - x))
    h = max(16, min(int(round(layer["h"] * height)), height - y))
    return max(0, min(x, width - 16)), max(0, min(y, height - 16)), w, h


def _with_opacity(tile: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return tile
    alpha = tile.getchannel("A").point(lambda a: int(a * opacity))
    tile.putalpha(alpha)
    return tile


def font_px(layer: dict, height: int) -> int:
    share = layer.get("font_size") or C.SIZE_RATIOS.get(layer.get("size") or "md", 0.045)
    return max(ABS_MIN_FONT, int(round(share * height)))


def fit(text: str, primary: Path | None, bold: bool, box_w: int, box_h: int, start_px: int,
        line_height: float, scrim: bool) -> tuple[Face, list[str], int, int, bool]:
    """``(face, lines, line_box, inner_pad, fits)`` at the biggest size that fits the box."""
    min_font = max(ABS_MIN_FONT, min(18, box_h // 3))
    size = max(start_px, min_font)
    inner_pad = max(int(box_w * 0.04), 10) if box_w > 60 else 2
    while True:
        face = Face(primary, bold, size)
        pad_x = int(size * 0.7) if scrim else 0
        pad_y = int(size * 0.5) if scrim else 0
        max_width = max(16, box_w - 2 * max(pad_x, inner_pad))
        lines = wrap(text, face, max_width)
        widest = max((face.width(line) for line in lines), default=0)
        line_box = max(1, int(round(size * line_height)))
        total = max(len(lines), 1) * line_box + 2 * pad_y
        fits_width = widest <= max_width
        if total <= box_h and fits_width:
            return face, lines, line_box, inner_pad, True
        floor = ABS_MIN_FONT if not fits_width else min_font
        if size <= floor:
            return face, lines, line_box, inner_pad, False
        size = max(floor, size - 3)


def _draw_line(draw: ImageDraw.ImageDraw, x: float, baseline: float, line: str, face: Face,
               fill: tuple[int, ...], report: Report | None) -> None:
    for chars, font, stroke in face.runs(line, report):
        draw.text((x + stroke, baseline), chars, font=font, fill=fill, anchor="ls",
                  stroke_width=stroke, stroke_fill=fill if stroke else None)
        x += font.getlength(chars) + 2 * stroke


def _text_tile(layer: dict, width: int, height: int, report: Report) -> tuple[Image.Image, int, int] | None:
    text = layer.get("text") or ""
    if layer.get("uppercase"):
        text = text.upper()
    if not text.strip():
        return None
    box_x, box_y, box_w, box_h = _px_box(layer, width, height)
    primary = None
    font = layer.get("font") or {}
    if font.get("file_id"):
        primary = F.font_path(font["file_id"])
        if primary is None:
            report.missing_files.append(layer["id"])
    color = C.rgb(layer.get("color") or "#FFFFFF")
    light = sum(color) > 382
    scrim = bool(layer.get("scrim"))
    face, lines, line_box, inner_pad, fits = fit(
        text, primary, bool(layer.get("bold")), box_w, box_h, font_px(layer, height),
        float(layer.get("line_height") or 1.28), scrim)
    block_h = len(lines) * line_box
    vertical = layer.get("vertical") or "middle"
    if vertical == "top":
        top = inner_pad
    elif vertical == "bottom":
        top = box_h - block_h - inner_pad
    else:
        top = (box_h - block_h) // 2
    top = max(0, min(top, box_h - block_h))
    shown = [line for i, line in enumerate(lines) if top + (i + 1) * line_box <= box_h + 1]
    if len(shown) < len(lines) or not fits:
        report.clipped.append(layer["id"])
    lines = shown
    block_h = len(lines) * line_box

    tile = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    if scrim and lines:
        pad = max(inner_pad, int(face.size * 0.5))
        y0, y1 = max(0, top - pad), min(box_h, top + block_h + pad)
        # a rounded plate on a clear ground, blurred: its edges fade instead of ending in a hard line
        band = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        ImageDraw.Draw(band).rounded_rectangle(
            (SCRIM_BLUR // 2, y0 + SCRIM_BLUR // 2, box_w - 1 - SCRIM_BLUR // 2, max(y0 + 1, y1 - 1 - SCRIM_BLUR // 2)),
            radius=14, fill=(0, 0, 0, 120) if light else (255, 255, 255, 110))
        tile.alpha_composite(band.filter(ImageFilter.GaussianBlur(SCRIM_BLUR)))
    draw = ImageDraw.Draw(tile)
    shadow = (0, 0, 0, 200) if light else (255, 255, 255, 160)
    offset = max(2, round(face.size * 0.03))
    align = layer.get("align") or "center"
    lead = (line_box - (face.ascent + face.descent)) / 2
    for i, line in enumerate(lines):
        line_w = face.width(line)
        if align == "left":
            x = inner_pad
        elif align == "right":
            x = box_w - inner_pad - line_w
        else:
            x = (box_w - line_w) / 2
        baseline = top + i * line_box + lead + face.ascent
        if layer.get("shadow"):
            _draw_line(draw, x + offset, baseline + offset, line, face, shadow, None)
        _draw_line(draw, x, baseline, line, face, (*color, 255), report)
    return _with_opacity(tile, float(layer.get("opacity", 1.0))), box_x, box_y


def _shape_tile(layer: dict, width: int, height: int) -> tuple[Image.Image, int, int]:
    box_x, box_y, box_w, box_h = _px_box(layer, width, height)
    alpha = int(round(255 * float(layer.get("opacity", 1.0))))
    fill = (*C.rgb(layer.get("fill") or "#111111"), alpha)
    tile = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    if layer.get("shape") == "ellipse":
        draw.ellipse((0, 0, box_w - 1, box_h - 1), fill=fill)
    else:
        radius = int(round(float(layer.get("radius") or 0) * min(width, height)))
        radius = min(radius, box_w // 2, box_h // 2)
        draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=radius, fill=fill)
    return tile, box_x, box_y


def _logo_tile(layer: dict, width: int, height: int, logo_file_id: int | None,
               report: Report) -> tuple[Image.Image, int, int] | None:
    file_id = layer.get("file_id") or logo_file_id
    if not file_id:
        return None
    try:
        data = files.read_bytes(int(file_id))
        logo = Image.open(io.BytesIO(data))
        logo = ImageOps.exif_transpose(logo).convert("RGBA")
    except (AppError, OSError, ValueError):
        report.missing_files.append(layer["id"])
        return None
    box_x, box_y, box_w, box_h = _px_box(layer, width, height)
    logo = ImageOps.contain(logo, (box_w, box_h), Image.LANCZOS)
    tile = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    tile.alpha_composite(logo, ((box_w - logo.width) // 2, (box_h - logo.height) // 2))
    return _with_opacity(tile, float(layer.get("opacity", 1.0))), box_x, box_y


def open_background(data: bytes, max_side: int = C.RENDER_MAX_SIDE) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise AppError("bad_image", 400, "The background does not open as a picture") from exc
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def render(background: bytes, layers: list[dict], *, logo_file_id: int | None = None,
           max_side: int = C.RENDER_MAX_SIDE) -> tuple[bytes, dict]:
    """``(png, report)``: the visible layers drawn bottom first over the background."""
    img = open_background(background, max_side)
    width, height = img.size
    report = Report(width=width, height=height)
    for layer in layers:
        if not layer.get("visible", True):
            continue
        if layer["type"] == "text":
            placed = _text_tile(layer, width, height, report)
        elif layer["type"] == "shape":
            placed = _shape_tile(layer, width, height)
        elif layer["type"] == "logo":
            placed = _logo_tile(layer, width, height, logo_file_id, report)
        else:
            placed = None
        if placed is not None:
            tile, x, y = placed
            img.alpha_composite(tile, (x, y))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue(), report.public()


__all__ = ["Face", "Report", "fit", "font_px", "open_background", "render", "wrap"]
