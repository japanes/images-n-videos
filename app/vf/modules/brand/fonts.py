"""Read an uploaded TTF/OTF font and guess its typography category locally,
without AI and without network.

Categories (module 06 uses the same words): serif, sans, mono, display, handwriting.

Detection order (ported from factory ``api/services/font_classifier.py``, minus
the Google Fonts catalog lookup):
  1. ``post.isFixedPitch``             -> mono
  2. ``OS/2.sFamilyClass`` (IBM class) -> serif / sans / display / handwriting
  3. PANOSE (``OS/2.panose``)          -> handwriting / display / sans / serif
  4. keywords in the font names        -> mono / handwriting / sans / serif / display
  5. fallback                          -> sans
The user can always change the category by hand.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont

from vf.core.errors import AppError

CATEGORIES = ("serif", "sans", "mono", "display", "handwriting")
DEFAULT_CATEGORY = "sans"

# IBM Font Class (high byte of OS/2.sFamilyClass).
# https://learn.microsoft.com/en-us/typography/opentype/spec/ibmfc
_IBM_CLASS = {
    1: "serif",  # Old Style Serifs
    2: "serif",  # Transitional Serifs
    3: "serif",  # Modern Serifs
    4: "serif",  # Clarendon Serifs
    5: "serif",  # Slab Serifs
    7: "serif",  # Free-form Serifs
    8: "sans",  # Sans Serif
    9: "display",  # Ornamentals
    10: "handwriting",  # Scripts
    12: "display",  # Symbolic
}

_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")


@dataclass
class FontInfo:
    family: str
    full_name: str
    style: str
    category: str
    detected_by: str  # fixed_pitch | ibm_class | panose | name | default
    weight: int | None = None
    italic: bool = False
    meta: dict = field(default_factory=dict)


def _panose_category(panose) -> str | None:
    """PANOSE byte 1 = family kind; for Latin Text byte 2 = serif style."""
    family = getattr(panose, "bFamilyType", 0)
    serif = getattr(panose, "bSerifStyle", 0)
    if family == 3:
        return "handwriting"
    if family in (4, 5):
        return "display"
    if family == 2:
        if serif in (11, 12, 13, 15):
            return "sans"
        if 2 <= serif <= 10 or serif == 14:
            return "serif"
    return None


def _name_category(name: str) -> str | None:
    name = name.lower()
    if not name:
        return None
    if "mono" in name:
        return "mono"
    if "script" in name or "hand" in name or "cursive" in name:
        return "handwriting"
    if "sans" in name:  # before "serif": "Sans Serif" is a sans
        return "sans"
    if "serif" in name:
        return "serif"
    if "display" in name or "decorative" in name:
        return "display"
    return None


def _names(tt: TTFont) -> dict[int, str]:
    out: dict[int, str] = {}
    table = tt.get("name")
    if table is None:
        return out
    # Prefer Windows English records, then anything readable.
    for record in sorted(table.names, key=lambda r: (r.platformID != 3, r.langID != 0x409)):
        if record.nameID in out or record.nameID not in (1, 2, 4, 16, 17):
            continue
        try:
            text = record.toUnicode().strip()
        except (UnicodeDecodeError, ValueError):
            continue
        if text:
            out[record.nameID] = text
    return out


def inspect_font(data: bytes) -> FontInfo:
    """Parse a TTF/OTF file. Raises ``font_unreadable`` when it is not one."""
    if data[:4] not in _MAGIC:
        raise AppError("font_unreadable", 400, "This is not a TTF or OTF font file")
    try:
        tt = TTFont(io.BytesIO(data), lazy=True)
    except Exception as exc:  # noqa: BLE001 - any parse failure means "not a font we can use"
        raise AppError("font_unreadable", 400, "The font file could not be read") from exc
    try:
        names = _names(tt)
        family = names.get(16) or names.get(1) or ""
        style = names.get(17) or names.get(2) or ""
        full_name = names.get(4) or " ".join(x for x in (family, style) if x)
        weight = None
        italic = False
        category = None
        detected_by = "default"
        post = tt.get("post")
        os2 = tt.get("OS/2")
        if os2 is not None:
            weight = int(getattr(os2, "usWeightClass", 0) or 0) or None
            italic = bool(getattr(os2, "fsSelection", 0) & 1)
        if post is not None and getattr(post, "isFixedPitch", 0):
            category, detected_by = "mono", "fixed_pitch"
        if category is None and os2 is not None:
            mapped = _IBM_CLASS.get((int(getattr(os2, "sFamilyClass", 0)) >> 8) & 0xFF)
            if mapped:
                category, detected_by = mapped, "ibm_class"
            else:
                mapped = _panose_category(getattr(os2, "panose", None))
                if mapped:
                    category, detected_by = mapped, "panose"
        if category is None:
            mapped = _name_category(" ".join(names.get(i, "") for i in (1, 4, 16)))
            if mapped:
                category, detected_by = mapped, "name"
        if not family:
            raise AppError("font_unreadable", 400, "The font file has no family name")
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError("font_unreadable", 400, "The font file could not be read") from exc
    finally:
        tt.close()
    return FontInfo(family=family[:120], full_name=full_name[:200], style=style[:60],
                    category=category or DEFAULT_CATEGORY, detected_by=detected_by,
                    weight=weight, italic=italic)
