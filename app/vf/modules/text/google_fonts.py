"""Google Fonts: search the catalog and add a font to a brand kit (factory ``google_fonts``).

The catalog is a snapshot kept in the repository (``data/google_fonts.json``: family, category,
subsets, weights), so search works offline and needs no API key. Adding a font downloads its TTF
from fonts.gstatic.com: the family's file list comes from ``fonts.google.com/download/list`` —
the same list the «Download family» button of the Google Fonts site uses — and only files on
fonts.gstatic.com are fetched. Fonts are free (OFL/Apache); nothing is paid and nothing is
journaled. Downloaded files are kept in ``cache/text/gfonts`` so a second kit does not fetch
them again.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from vf.core import db, files
from vf.core.config import get_config
from vf.core.errors import AppError, NotFound
from vf.modules import brand
from vf.modules.text import common as C

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "google_fonts.json"
LIST_URL = "https://fonts.google.com/download/list"
FILE_HOSTS = ("fonts.gstatic.com",)
TIMEOUT = 30.0
MAX_FONT_BYTES = 20 * 1024 * 1024
MAX_PAGE = 120
CATEGORIES = ("sans", "serif", "display", "handwriting", "mono")

Fetch = Callable[[str, dict | None], Awaitable[bytes]]


async def _http_get(url: str, params: dict | None = None) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise AppError("fonts_unreachable", 503, "Google Fonts cannot be reached", detail=str(exc)[:300]) from exc
    if resp.status_code >= 400:
        raise AppError("font_download_failed", 502, "Google Fonts did not give the font",
                       status=resp.status_code, detail=resp.text[:300])
    if len(resp.content) > MAX_FONT_BYTES:
        raise AppError("file_too_large", 413, "The font file is too large")
    return resp.content


# Tests put a fake here; nothing else reaches the network.
fetch: Fetch = _http_get


# --- catalog -------------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    families = [f for f in data.get("families") or [] if isinstance(f, dict) and f.get("family")]
    return {"taken_at": data.get("taken_at"), "families": families,
            "by_name": {f["family"].lower(): f for f in families}}


def entry(family: Any) -> dict:
    found = catalog()["by_name"].get(str(family or "").strip().lower())
    if found is None:
        raise NotFound("google_font", family=family)
    return found


def public(item: dict) -> dict:
    subsets = item.get("subsets") or []
    return {"family": item["family"], "category": item.get("category") or "sans",
            "cyrillic": "cyrillic" in subsets, "weights": item.get("weights") or [],
            "italic": bool(item.get("italic")), "variable": bool(item.get("variable"))}


def search(q: str | None = None, *, category: str | None = None, cyrillic: bool = False,
           offset: int = 0, limit: int = 60) -> dict:
    """``{items, total, taken_at}``: the catalog by popularity, filtered by name, category, Cyrillic."""
    needle = (q or "").strip().lower()
    if category and category not in CATEGORIES:
        raise AppError("bad_request", 400, "Unknown font category", category=category)
    found = []
    for item in catalog()["families"]:
        if needle and needle not in item["family"].lower():
            continue
        if category and item.get("category") != category:
            continue
        if cyrillic and "cyrillic" not in (item.get("subsets") or []):
            continue
        found.append(item)
    if needle:  # a name that starts with what was typed comes first
        found.sort(key=lambda f: (not f["family"].lower().startswith(needle), f.get("popularity") or 1e9))
    offset = max(0, int(offset or 0))
    limit = min(max(1, int(limit or 60)), MAX_PAGE)
    return {"items": [public(f) for f in found[offset:offset + limit]], "total": len(found),
            "taken_at": catalog()["taken_at"], "categories": list(CATEGORIES)}


# --- download ------------------------------------------------------------------------------


def _slug(family: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", family).strip("-") or "font"


def _cache_path(family: str) -> Path:
    return get_config().cache_dir / "text" / "gfonts" / f"{_slug(family)}.ttf"


def pick_file(refs: list[dict]) -> dict | None:
    """The upright regular face: a static ``-Regular.ttf``, else the upright variable file."""
    ttf = [r for r in refs if isinstance(r, dict) and str(r.get("filename", "")).lower().endswith(".ttf")
           and str(r.get("url", ""))]
    upright = [r for r in ttf if "italic" not in str(r["filename"]).lower()]
    for test in (lambda name: name.endswith("-regular.ttf"),
                 lambda name: "variablefont" in name,
                 lambda name: True):
        for ref in upright or ttf:
            if test(str(ref["filename"]).lower().rsplit("/", 1)[-1]):
                return ref
    return None


def _file_list(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8", "replace")
    if text.startswith(")]}'"):  # Google's guard against JSON hijacking
        text = text[4:]
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AppError("font_download_failed", 502, "Google Fonts answered with something else") from exc
    manifest = data.get("manifest") if isinstance(data, dict) else None
    refs = (manifest or {}).get("fileRefs")
    return refs if isinstance(refs, list) else []


async def font_bytes(family: str) -> bytes:
    """The TTF of a catalog family (from the cache, else downloaded)."""
    item = entry(family)
    path = _cache_path(item["family"])
    if path.is_file() and path.stat().st_size > 0:
        return path.read_bytes()
    ref = pick_file(_file_list(await fetch(LIST_URL, {"family": item["family"]})))
    if ref is None:
        raise AppError("font_download_failed", 502, "Google Fonts has no TTF file for this font",
                       family=item["family"])
    url = str(ref["url"]).replace("http://", "https://", 1)
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host not in FILE_HOSTS:
        raise AppError("font_download_failed", 502, "The font file is not on fonts.gstatic.com", url=url[:200])
    data = await fetch(url, None)
    if not data:
        raise AppError("font_download_failed", 502, "Google Fonts gave an empty file")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


async def add_to_kit(kit_id: Any, family: Any) -> dict:
    """Download the family's TTF and add it to the kit as a font (``brand.add_catalog_font``)."""
    try:
        kit_id = int(kit_id)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "A brand kit id is expected") from None
    kit = db.get("brand_kits", kit_id)
    if kit is None:
        raise NotFound("brand_kit", id=kit_id)
    item = entry(family)
    taken = db.fetch_value("SELECT COUNT(*) FROM brand_assets WHERE kit_id = ? AND kind = 'font'"
                           " AND google_family = ?", (kit_id, item["family"]), 0)
    if taken:
        raise AppError("font_in_kit", 409, "This font is already in the kit", family=item["family"])
    data = await font_bytes(item["family"])
    info = brand.inspect_font(data)  # raises font_unreadable
    saved = files.save_bytes(data, mime="font/ttf", name=f"{_slug(item['family'])}.ttf", origin="upload",
                             title=f"{kit['name']}: {item['family']}", source_type=C.SOURCE_FONT,
                             source_id=kit_id)
    try:
        asset = brand.add_catalog_font(
            kit_id, item["family"], item.get("category") or "sans", file_id=saved["id"], name=item["family"],
            meta={"weight": info.weight, "italic": info.italic, "style": info.style,
                  "cyrillic": "cyrillic" in (item.get("subsets") or []), "catalog_taken_at": catalog()["taken_at"]})
    except AppError:
        files.delete(saved["id"], force=True)
        raise
    C.log.info("text: Google font %s added to kit %s", item["family"], kit_id)
    return asset


__all__ = ["add_to_kit", "catalog", "entry", "font_bytes", "pick_file", "search"]
