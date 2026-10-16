"""Picture helpers of the studio, all local (Pillow): fitting the answer to the
frame, the marked copy for a correction, downscaling what goes to the model, and
an object's place in words.

``fit_to_frame`` and ``marked_copy`` are ported from factory
``api/services/image/frame.py`` and ``marker.py``; ``area_words`` from
``image/segment.py``.
"""

from __future__ import annotations

import io
import logging
from typing import NamedTuple

from PIL import Image, ImageDraw

log = logging.getLogger("vf.studio")

# How far the returned shape may sit from the requested one and still count as
# the same frame (a fraction of a per cent in practice).
MAX_ASPECT_DRIFT = 0.03

# The marked copy: a bright magenta rectangle with a thin dark edge, so it reads
# on light and dark pictures alike. The colour name goes into the prompt.
MARKER_COLOUR = (255, 0, 255)
MARKER_COLOUR_NAME = "bright magenta"
MARKER_EDGE = (16, 16, 16)
BAND_SHARE = 0.005
MIN_BAND = 3


class Fit(NamedTuple):
    """``image`` is None when the answer already had the right size (keep the
    bytes as they are). ``how``: exact | fitted | stretched."""

    image: bytes | None
    how: str
    note: str


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fit_on_base(img: Image.Image, base_bytes: bytes, width: int, height: int) -> Fit | None:
    """Scale by one number and complete the empty sliver from the picture being corrected."""
    try:
        canvas = Image.open(io.BytesIO(base_bytes))
        canvas.load()
    except Exception:  # noqa: BLE001
        log.warning("cannot read the picture being corrected", exc_info=True)
        return None
    mode = "RGBA" if "A" in img.getbands() or "A" in canvas.getbands() else "RGB"
    canvas = canvas.convert(mode)
    if canvas.size != (width, height):
        canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    scale = min(width / img.width, height / img.height)
    new_w = max(1, min(width, int(round(img.width * scale))))
    new_h = max(1, min(height, int(round(img.height * scale))))
    answer = img.convert(mode).resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas.paste(answer, ((width - new_w) // 2, (height - new_h) // 2))
    note = (f"kept the proportions it drew and completed {width - new_w} px of width and "
            f"{height - new_h} px of height from the picture being corrected")
    return Fit(_png(canvas), "fitted", note)


def fit_to_frame(image_bytes: bytes, width: int, height: int, base_bytes: bytes | None = None) -> Fit:
    """The model's answer at exactly ``width`` x ``height``.

    With ``base_bytes`` (the picture the answer corrects) the frame is completed
    rather than stretched, so a chain of corrections adds no distortion. Raises
    whatever Pillow raises on bytes that are not a picture.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if img.width == width and img.height == height:
        return Fit(None, "exact", "already the size of the frame")
    if base_bytes:
        wanted = width / height
        drift = abs(img.width / img.height - wanted) / wanted
        if drift <= MAX_ASPECT_DRIFT:
            fitted = _fit_on_base(img, base_bytes, width, height)
            if fitted is not None:
                return fitted
    note = f"stretched {img.width}x{img.height} to {width}x{height}"
    return Fit(_png(img.resize((width, height), Image.Resampling.LANCZOS)), "stretched", note)


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.width, img.height


def aspect_target(width: int, height: int, aspect: str) -> tuple[int, int]:
    """The frame for an answer of ``width`` x ``height`` when no output size is set:
    the model's own width, the height that makes the asked ratio exact."""
    a, b = (int(x) for x in aspect.split(":"))
    return width, max(1, int(round(width * b / a)))


# ── the marked copy ─────────────────────────────────────────────────────────

def _span(start: float, size: float, limit: int) -> tuple[int, int]:
    lo = min(max(float(start), 0.0), 1.0)
    hi = min(max(float(start) + float(size), 0.0), 1.0)
    a, b = int(round(lo * limit)), int(round(hi * limit))
    if b - a < 2:
        b = min(limit, a + 2)
        a = max(0, b - 2)
    return a, b


def _grow(rect: tuple[int, int, int, int], by: int, width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return max(0, x0 - by), max(0, y0 - by), min(width - 1, x1 + by), min(height - 1, y1 + by)


def marked_copy(image_bytes: bytes | None, box: dict | None) -> bytes | None:
    """The picture with a magenta rectangle around ``box`` ({x, y, w, h} in fractions),
    as PNG. None when there is nothing sensible to draw."""
    if not image_bytes or not isinstance(box, dict):
        return None
    try:
        w, h = float(box.get("w", 0)), float(box.get("h", 0))
        if w <= 0 or h <= 0:
            return None
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.width < 8 or img.height < 8:
            return None
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        x0, x1 = _span(box.get("x", 0), w, img.width)
        y0, y1 = _span(box.get("y", 0), h, img.height)
        band = max(MIN_BAND, int(round(min(img.width, img.height) * BAND_SHARE)))
        rect = _grow((x0, y0, x1, y1), band, img.width, img.height)
        draw = ImageDraw.Draw(img)
        draw.rectangle(_grow(rect, 2, img.width, img.height), outline=MARKER_EDGE, width=band + 2)
        draw.rectangle(rect, outline=MARKER_COLOUR, width=band)
        return _png(img)
    except Exception:  # noqa: BLE001
        log.warning("could not draw the marked copy", exc_info=True)
        return None


# ── what goes to the model ──────────────────────────────────────────────────

def shrink(data: bytes, mime: str, *, max_side: int = 1024, quality: int = 88) -> tuple[bytes, str]:
    """A picture no larger than ``max_side`` on its long side, as JPEG (transparency on
    white). Small JPEGs are sent as they are; unreadable bytes are returned unchanged."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if max(img.size) <= max_side and mime == "image/jpeg":
                return data, mime
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                ground = Image.new("RGB", img.size, (255, 255, 255))
                ground.paste(img, mask=img.split()[-1])
                img = ground
            elif img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        log.warning("could not downscale a picture; sent as it is", exc_info=True)
        return data, mime


def to_width(data: bytes, mime: str, *, width: int = 1024, quality: int = 80) -> tuple[bytes, str]:
    """The picture at most ``width`` wide, as JPEG: what "find objects" looks at."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGB")
            if img.width > width:
                img = img.resize((width, max(1, int(round(img.height * width / img.width)))),
                                 Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return data, mime


def area_words(box: dict) -> str:
    """Where an object sits, in words for the prompt (box in fractions)."""
    left, top = float(box.get("x", 0)) * 100, float(box.get("y", 0)) * 100
    width, height = float(box.get("w", 0)) * 100, float(box.get("h", 0)) * 100
    share = width * height / 100
    taking = "less than 1%" if share < 1 else f"about {share:.0f}%"
    return (f"between {left:.0f}% and {left + width:.0f}% from the left edge and between "
            f"{top:.0f}% and {top + height:.0f}% from the top edge, taking up {taking} of the picture")
