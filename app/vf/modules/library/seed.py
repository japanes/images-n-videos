"""Built-in library from ``app/seeds/library`` — synced into the database on every start.

* categories are matched by ``slug``, built-in styles by ``code``;
* a changed seed overwrites the built-in row (built-ins are read-only in the app);
* something gone from the seed is not deleted: it is marked ``removed_from_seed``
  and hidden, so works that point at it keep their text;
* own styles (``code IS NULL``) are never touched.

The seed itself is produced once by ``scripts/export-factory-library.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vf.core import db

log = logging.getLogger("vf.library")

SEED_DIR = Path(__file__).resolve().parents[3] / "seeds" / "library"
KINDS = ("style", "photo_style")

_CATEGORY_FIELDS = ("parent", "depth", "sort", "title", "title_uk", "title_en")
_STYLE_FIELDS = ("kind", "title", "description", "prompt", "text_zones_json", "category", "sort", "preview_seed")


def seed_dir() -> Path:
    return SEED_DIR


def preview_path(rel: str | None, root: Path | None = None) -> Path | None:
    """Absolute path of a seed preview; None for anything outside the seed folder or missing."""
    if not rel:
        return None
    base = (root or SEED_DIR).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        return None
    return p


def load(root: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Seed categories and styles, checked. A broken seed is a bug in the release: it raises."""
    base = root or SEED_DIR
    cats = json.loads((base / "categories.json").read_text(encoding="utf-8"))["categories"]
    styles = json.loads((base / "styles.json").read_text(encoding="utf-8"))["styles"]
    slugs = set()
    for c in cats:
        if not c.get("slug") or not c.get("title"):
            raise ValueError(f"library seed: category without slug/title: {c!r}")
        if c["slug"] in slugs:
            raise ValueError(f"library seed: duplicate category {c['slug']}")
        slugs.add(c["slug"])
    codes = set()
    for s in styles:
        if not s.get("code") or not str(s.get("prompt") or "").strip() or not s.get("title"):
            raise ValueError(f"library seed: style without code/title/prompt: {s.get('code')!r}")
        if s["code"] in codes:
            raise ValueError(f"library seed: duplicate style {s['code']}")
        if s.get("kind") not in KINDS:
            raise ValueError(f"library seed: {s['code']} has kind {s.get('kind')!r}")
        codes.add(s["code"])
    return cats, styles


def _category_values(c: dict) -> dict[str, Any]:
    return {"parent": c.get("parent"), "depth": int(c.get("depth") or 0), "sort": int(c.get("sort") or 0),
            "title": str(c["title"]), "title_uk": c.get("title_uk"), "title_en": c.get("title_en")}


def _style_values(s: dict) -> dict[str, Any]:
    zones = s.get("text_zones")
    return {"kind": s["kind"], "title": str(s["title"]), "description": str(s.get("description") or ""),
            "prompt": str(s["prompt"]),
            "text_zones_json": json.dumps(zones, ensure_ascii=False, sort_keys=True) if zones else None,
            "category": s.get("category"), "sort": int(s.get("sort") or 0), "preview_seed": s.get("preview")}


def sync(root: Path | None = None) -> dict[str, int]:
    """Bring the database in line with the seed. Returns counts for the log and tests."""
    cats, styles = load(root)
    stats = {"categories_added": 0, "categories_updated": 0, "categories_removed": 0,
             "styles_added": 0, "styles_updated": 0, "styles_removed": 0}
    now = db.now()
    with db.tx():
        existing = {r["slug"]: r for r in db.fetch_all("SELECT * FROM preset_categories")}
        for c in cats:
            values = _category_values(c)
            row = existing.get(c["slug"])
            if row is None:
                db.insert("preset_categories", {"slug": c["slug"], **values, "builtin": 1,
                                                "removed_from_seed": 0, "updated_at": now})
                stats["categories_added"] += 1
            elif any(row.get(k) != values[k] for k in _CATEGORY_FIELDS) or row["removed_from_seed"]:
                db.execute(
                    "UPDATE preset_categories SET parent = ?, depth = ?, sort = ?, title = ?, title_uk = ?, "
                    "title_en = ?, builtin = 1, removed_from_seed = 0, updated_at = ? WHERE slug = ?",
                    (*[values[k] for k in _CATEGORY_FIELDS], now, c["slug"]))
                stats["categories_updated"] += 1
        seed_slugs = {c["slug"] for c in cats}
        for slug, row in existing.items():
            if slug not in seed_slugs and row["builtin"] and not row["removed_from_seed"]:
                db.execute("UPDATE preset_categories SET removed_from_seed = 1, updated_at = ? WHERE slug = ?",
                           (now, slug))
                stats["categories_removed"] += 1

        rows = {r["code"]: r for r in db.fetch_all(
            "SELECT id, code, kind, title, description, prompt, text_zones_json AS zones_raw, category, sort, "
            "preview_seed, removed_from_seed, is_builtin FROM presets WHERE code IS NOT NULL")}
        for s in styles:
            values = _style_values(s)
            row = rows.get(s["code"])
            if row is None:
                db.insert("presets", {"code": s["code"], **values, "is_builtin": 1, "removed_from_seed": 0,
                                      "created_at": now, "updated_at": now})
                stats["styles_added"] += 1
                continue
            current = {**row, "text_zones_json": row["zones_raw"]}
            if (any(current.get(k) != values[k] for k in _STYLE_FIELDS) or row["removed_from_seed"]
                    or not row["is_builtin"]):
                # text_zones_json is already a JSON string: db.update stores strings as they are.
                db.update("presets", row["id"], {**values, "is_builtin": 1, "removed_from_seed": 0,
                                                 "updated_at": now})
                stats["styles_updated"] += 1
        seed_codes = {s["code"] for s in styles}
        for code, row in rows.items():
            if code not in seed_codes and not row["removed_from_seed"]:
                db.execute("UPDATE presets SET removed_from_seed = 1, updated_at = ? WHERE id = ?", (now, row["id"]))
                stats["styles_removed"] += 1
    changed = {k: v for k, v in stats.items() if v}
    if changed:
        log.info("library seed synced: %s", changed)
    return stats
