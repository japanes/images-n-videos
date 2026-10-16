"""Fonts the renderer can use: the brand kit's own files and the bundled Roboto.

Roboto (OFL, ``fonts/``) covers Latin and Cyrillic. It draws every character a
brand font lacks, so a Latin-only brand font never leaves boxes in a Cyrillic line.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont
from PIL import ImageFont

from vf.core import db, files
from vf.core.errors import AppError
from vf.modules.text.common import log

FONT_DIR = Path(__file__).resolve().parent / "fonts"
REGULAR = FONT_DIR / "Roboto-Regular.ttf"
BOLD = FONT_DIR / "Roboto-Bold.ttf"
FALLBACK_FAMILY = "Roboto"
FONT_MIMES = ("font/ttf", "font/otf", "font/sfnt", "application/x-font-ttf", "application/font-sfnt")


def _mtime(path: str | Path) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


@functools.lru_cache(maxsize=64)
def _coverage(path: str, mtime: float) -> frozenset[int]:
    try:
        with TTFont(path, lazy=True, fontNumber=0) as tt:
            cmap = tt.getBestCmap() or {}
        return frozenset(cmap)
    except Exception as exc:  # a broken file draws nothing
        log.warning("text: font %s has no readable character map (%s)", path, exc)
        return frozenset()


def coverage(path: str | Path) -> frozenset[int]:
    """The code points the font has a glyph for."""
    return _coverage(str(path), _mtime(path))


@functools.lru_cache(maxsize=256)
def _truetype(path: str, mtime: float, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def truetype(path: str | Path, size: int) -> ImageFont.FreeTypeFont:
    return _truetype(str(path), _mtime(path), max(4, int(size)))


def fallback_path(bold: bool = False) -> Path:
    return BOLD if bold else REGULAR


def font_path(file_id: Any) -> Path | None:
    """The file of a font on disk; None when it is gone, not a font or does not open."""
    try:
        row = files.get(int(file_id))
    except (AppError, TypeError, ValueError):
        return None
    mime = str(row.get("mime") or "")
    if not (mime.startswith("font/") or mime in FONT_MIMES):
        return None
    path = files.path_of(row)
    if not Path(path).is_file():
        return None
    if not coverage(path):
        return None
    return Path(path)


def _from_asset(row: dict) -> dict:
    meta = row.get("meta_json") or {}
    path = font_path(row["file_id"]) if row.get("file_id") else None
    return {"asset_id": row["id"], "file_id": row.get("file_id"), "family": row.get("font_family") or row["name"],
            "name": row["name"], "category": row.get("font_category"), "source": row.get("font_source"),
            "weight": meta.get("weight"), "italic": bool(meta.get("italic")), "renderable": path is not None}


def _from_snapshot(font: dict) -> dict:
    path = font_path(font["file_id"]) if font.get("file_id") else None
    return {"asset_id": None, "file_id": font.get("file_id"), "family": font.get("family") or font.get("name"),
            "name": font.get("name") or font.get("family"), "category": font.get("category"),
            "source": font.get("source"), "weight": None, "italic": False, "renderable": path is not None}


def kit_fonts(kit_id: int | None, snapshot: dict | None = None) -> list[dict]:
    """The fonts the editor offers: the kit as it is now, else the work's brand snapshot.

    Each: ``{asset_id, file_id, family, name, category, source, weight, italic, renderable}``;
    ``renderable`` False = no file to draw with (the bundled Roboto draws instead)."""
    if kit_id and db.get("brand_kits", int(kit_id)) is not None:
        rows = db.fetch_all("SELECT * FROM brand_assets WHERE kit_id = ? AND kind = 'font' ORDER BY sort, id",
                            (int(kit_id),))
        return [_from_asset(r) for r in rows]
    if snapshot:
        return [_from_snapshot(f) for f in snapshot.get("fonts") or [] if isinstance(f, dict)]
    return []


def kit_logos(kit_id: int | None, snapshot: dict | None = None) -> list[dict]:
    """``[{file_id, name}]`` of the brand's logos (kit now, else the snapshot)."""
    if kit_id and db.get("brand_kits", int(kit_id)) is not None:
        rows = db.fetch_all(
            "SELECT file_id, name FROM brand_assets WHERE kit_id = ? AND kind = 'logo' AND file_id IS NOT NULL "
            "ORDER BY sort, id", (int(kit_id),))
        return [{"file_id": r["file_id"], "name": r["name"]} for r in rows]
    if snapshot:
        return [{"file_id": logo["file_id"], "name": logo.get("name") or ""}
                for logo in snapshot.get("logos") or [] if isinstance(logo, dict) and logo.get("file_id")]
    return []


def kit_colors(kit_id: int | None, snapshot: dict | None = None) -> list[dict]:
    if kit_id:
        row = db.get("brand_kits", int(kit_id))
        if row is not None:
            return list(row.get("colors_json") or [])
    return list((snapshot or {}).get("colors") or [])


__all__ = ["BOLD", "FALLBACK_FAMILY", "REGULAR", "coverage", "fallback_path", "font_path", "kit_colors",
           "kit_fonts", "kit_logos", "truetype"]
