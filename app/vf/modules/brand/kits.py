"""Brand kits: colors, tone, fonts, logos, style references and brand elements.

A work (studio, chat) does not link to a kit: it keeps a *snapshot* taken with
``snapshot_kit`` and can re-take it ("update from kit") when ``kit_changed``
says the kit was edited since.
"""

from __future__ import annotations

import re
from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.modules.brand import fonts
from vf.modules.brand.common import (
    MAX_FONT_BYTES,
    SOURCE_ASSET,
    check_image,
    clean_block,
    clean_text,
    drop_own_file,
    publish,
    save_upload,
)

ELEMENT_KINDS = ("logo", "frame", "sticker", "plate", "badge", "background", "other")
IMAGE_KINDS = ("reference", *ELEMENT_KINDS)
ASSET_KINDS = ("font", *IMAGE_KINDS)
FONT_SOURCES = ("upload", "google")

MAX_NAME = 80
MAX_COLORS = 16
MAX_COLOR_LABEL = 40
MAX_TONE = 2000
MAX_ASSET_NAME = 120
MAX_HINT = 300
MAX_NOTE = 1000
MAX_ASSETS_PER_KIND = 60

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# ── reading ─────────────────────────────────────────────────────────────────


def _kit_row(kit_id: int) -> dict:
    row = db.get("brand_kits", kit_id)
    if row is None:
        raise NotFound("brand_kit", id=kit_id)
    return row


def _asset_row(asset_id: int) -> dict:
    row = db.get("brand_assets", asset_id)
    if row is None:
        raise NotFound("brand_asset", id=asset_id)
    return row


def _file_public(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    try:
        return files.public(files.get(file_id))
    except AppError:
        return None


def asset_public(row: dict) -> dict:
    out = {
        "id": row["id"], "kit_id": row["kit_id"], "kind": row["kind"], "name": row["name"],
        "position_hint": row["position_hint"], "note": row["note"], "sort": row["sort"],
        "file": _file_public(row["file_id"]), "file_id": row["file_id"], "created_at": row["created_at"],
    }
    if row["kind"] == "font":
        meta = row.get("meta_json") or {}
        out["font"] = {
            "family": row["font_family"], "category": row["font_category"], "source": row["font_source"],
            "google_family": row["google_family"], "weight": meta.get("weight"),
            "italic": bool(meta.get("italic")), "style": meta.get("style") or "",
            "detected_category": meta.get("detected_category"), "detected_by": meta.get("detected_by"),
        }
    return out


def _assets(kit_id: int) -> list[dict]:
    return db.fetch_all("SELECT * FROM brand_assets WHERE kit_id = ? ORDER BY kind, sort, id", (kit_id,))


def kit_public(row: dict, *, with_assets: bool = True) -> dict:
    assets = _assets(row["id"])
    counts: dict[str, int] = {}
    for a in assets:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
    logo = next((a for a in assets if a["kind"] == "logo"), None)
    out = {
        "id": row["id"], "name": row["name"], "colors": row["colors_json"] or [], "tone": row["tone"],
        "sort": row["sort"], "revision": row["revision"], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "counts": counts, "logo": _file_public(logo["file_id"]) if logo else None,
        "fonts": [{"family": a["font_family"], "category": a["font_category"]}
                  for a in assets if a["kind"] == "font"],
    }
    if with_assets:
        out["assets"] = [asset_public(a) for a in assets]
    return out


def list_kits() -> list[dict]:
    rows = db.fetch_all("SELECT * FROM brand_kits ORDER BY sort, id")
    return [kit_public(r, with_assets=False) for r in rows]


def get_kit(kit_id: int) -> dict:
    return kit_public(_kit_row(kit_id))


# ── kits ────────────────────────────────────────────────────────────────────


def _touch(kit_id: int) -> None:
    db.execute("UPDATE brand_kits SET revision = revision + 1, updated_at = ? WHERE id = ?", (db.now(), kit_id))


def normalize_colors(colors: Any) -> list[dict]:
    if colors is None:
        return []
    if not isinstance(colors, list):
        raise AppError("bad_colors", 400, "colors must be a list")
    if len(colors) > MAX_COLORS:
        raise AppError("too_many_colors", 400, "Too many colors", max=MAX_COLORS)
    out = []
    for item in colors:
        raw = item.get("hex") if isinstance(item, dict) else item
        m = _HEX.match(str(raw or "").strip())
        if not m:
            raise AppError("bad_color", 400, "A color must look like #1A2B3C", value=str(raw))
        hex6 = m.group(1)
        if len(hex6) == 3:
            hex6 = "".join(c * 2 for c in hex6)
        label = clean_text(item.get("label") if isinstance(item, dict) else "", MAX_COLOR_LABEL)
        out.append({"hex": f"#{hex6.upper()}", "label": label})
    return out


def create_kit(name: str, *, colors: Any = None, tone: str = "") -> dict:
    name = clean_text(name, MAX_NAME)
    if not name:
        raise AppError("name_required", 400, "Give the kit a name")
    now = db.now()
    sort = int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) + 1 FROM brand_kits", default=1))
    kit_id = db.insert("brand_kits", {"name": name, "colors_json": normalize_colors(colors),
                                      "tone": clean_block(tone, MAX_TONE), "sort": sort,
                                      "created_at": now, "updated_at": now})
    publish("kit", kit_id=kit_id)
    return get_kit(kit_id)


def update_kit(kit_id: int, *, name: str | None = None, colors: Any = None, tone: str | None = None) -> dict:
    _kit_row(kit_id)
    values: dict[str, Any] = {}
    if name is not None:
        name = clean_text(name, MAX_NAME)
        if not name:
            raise AppError("name_required", 400, "Give the kit a name")
        values["name"] = name
    if colors is not None:
        values["colors_json"] = normalize_colors(colors)
    if tone is not None:
        values["tone"] = clean_block(tone, MAX_TONE)
    if values:
        db.update("brand_kits", kit_id, values)
        _touch(kit_id)
        publish("kit", kit_id=kit_id)
    return get_kit(kit_id)


def delete_kit(kit_id: int) -> None:
    _kit_row(kit_id)
    file_ids = [a["file_id"] for a in _assets(kit_id) if a["file_id"]]
    with db.tx():
        db.execute("DELETE FROM brand_assets WHERE kit_id = ?", (kit_id,))
        db.delete("brand_kits", kit_id)
    for fid in file_ids:
        drop_own_file(fid, SOURCE_ASSET)
    publish("kit_deleted", kit_id=kit_id)


# ── assets ──────────────────────────────────────────────────────────────────


def _next_sort(kit_id: int, kind: str) -> int:
    return int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) + 1 FROM brand_assets WHERE kit_id = ? AND kind = ?",
                              (kit_id, kind), default=1))


def _check_room(kit_id: int, kind: str) -> None:
    count = db.fetch_value("SELECT COUNT(*) FROM brand_assets WHERE kit_id = ? AND kind = ?", (kit_id, kind),
                           default=0)
    if count >= MAX_ASSETS_PER_KIND:
        raise AppError("too_many_assets", 400, "This kit has too many items of this kind",
                       max=MAX_ASSETS_PER_KIND)


def _insert_asset(kit_id: int, kind: str, **values: Any) -> dict:
    asset_id = db.insert("brand_assets", {"kit_id": kit_id, "kind": kind, "sort": _next_sort(kit_id, kind),
                                          "created_at": db.now(), **values})
    _touch(kit_id)
    publish("asset", kit_id=kit_id, asset_id=asset_id)
    return asset_public(_asset_row(asset_id))


def _stem(name: str | None) -> str:
    if not name:
        return ""
    stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return clean_text(stem.rsplit(".", 1)[0] if "." in stem else stem, MAX_ASSET_NAME)


def add_image_asset(kit_id: int, kind: str, data: bytes, *, filename: str | None = None,
                    name: str | None = None) -> dict:
    """Upload a logo, a style reference or a brand element picture."""
    kit = _kit_row(kit_id)
    if kind not in IMAGE_KINDS:
        raise AppError("bad_kind", 400, "Unknown kind", kind=kind)
    _check_room(kit_id, kind)
    mime = check_image(data, filename)
    row = save_upload(data, mime=mime, name=filename, source_type=SOURCE_ASSET, source_id=kit_id,
                      title=f"{kit['name']}: {name or _stem(filename) or kind}")
    return _insert_asset(kit_id, kind, file_id=row["id"], name=clean_text(name, MAX_ASSET_NAME) or _stem(filename))


def add_image_asset_from_file(kit_id: int, kind: str, file_id: int, *, name: str | None = None) -> dict:
    """Use a picture that is already stored (media library, a generated image)."""
    _kit_row(kit_id)
    if kind not in IMAGE_KINDS:
        raise AppError("bad_kind", 400, "Unknown kind", kind=kind)
    _check_room(kit_id, kind)
    row = files.get(file_id)
    if row["mime"] not in ("image/png", "image/jpeg", "image/webp"):
        raise AppError("bad_image_type", 400, "Only PNG, JPEG and WebP pictures are supported")
    return _insert_asset(kit_id, kind, file_id=file_id,
                         name=clean_text(name, MAX_ASSET_NAME) or _stem(row.get("original_name") or row.get("title")))


def add_font_upload(kit_id: int, data: bytes, *, filename: str | None = None) -> dict:
    """Upload a TTF/OTF font; family and category are read from the file (no AI)."""
    kit = _kit_row(kit_id)
    _check_room(kit_id, "font")
    if not data:
        raise AppError("empty_file", 400, "The file is empty")
    if len(data) > MAX_FONT_BYTES:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=MAX_FONT_BYTES // 1024 // 1024)
    info = fonts.inspect_font(data)
    ext = "otf" if data[:4] == b"OTTO" else "ttf"
    mime = f"font/{ext}"
    base = _stem(filename) or info.family
    row = save_upload(data, mime=mime, name=f"{base}.{ext}", source_type=SOURCE_ASSET, source_id=kit_id,
                      title=f"{kit['name']}: {info.full_name or info.family}")
    return _insert_asset(
        kit_id, "font", file_id=row["id"], name=clean_text(info.full_name or info.family, MAX_ASSET_NAME),
        font_family=info.family, font_category=info.category, font_source="upload",
        meta_json={"weight": info.weight, "italic": info.italic, "style": info.style,
                   "detected_category": info.category, "detected_by": info.detected_by},
    )


def add_catalog_font(kit_id: int, family: str, category: str, *, file_id: int | None = None,
                     name: str | None = None, meta: dict | None = None) -> dict:
    """For module 06: a font picked from the Google Fonts catalog (TTF downloaded by module 06)."""
    _kit_row(kit_id)
    _check_room(kit_id, "font")
    family = clean_text(family, MAX_ASSET_NAME)
    if not family:
        raise AppError("name_required", 400, "Font family is empty")
    if category not in fonts.CATEGORIES:
        raise AppError("bad_font_category", 400, "Unknown font category", category=category)
    if file_id:
        files.get(file_id)
    return _insert_asset(kit_id, "font", file_id=file_id, name=clean_text(name, MAX_ASSET_NAME) or family,
                         font_family=family, font_category=category, font_source="google", google_family=family,
                         meta_json=meta or {})


def update_asset(asset_id: int, *, name: str | None = None, position_hint: str | None = None,
                 note: str | None = None, kind: str | None = None, font_category: str | None = None) -> dict:
    row = _asset_row(asset_id)
    values: dict[str, Any] = {}
    if name is not None:
        values["name"] = clean_text(name, MAX_ASSET_NAME)
    if position_hint is not None:
        values["position_hint"] = clean_block(position_hint, MAX_HINT)
    if note is not None:
        values["note"] = clean_block(note, MAX_NOTE)
    if kind is not None and kind != row["kind"]:
        # Pictures may move between "reference" and the element kinds; fonts stay fonts.
        if row["kind"] == "font" or kind not in IMAGE_KINDS:
            raise AppError("bad_kind", 400, "This item cannot become that kind", kind=kind)
        _check_room(row["kit_id"], kind)
        values["kind"] = kind
        values["sort"] = _next_sort(row["kit_id"], kind)
    if font_category is not None:
        if row["kind"] != "font" or font_category not in fonts.CATEGORIES:
            raise AppError("bad_font_category", 400, "Unknown font category", category=font_category)
        values["font_category"] = font_category
    if values:
        db.update("brand_assets", asset_id, values)
        _touch(row["kit_id"])
        publish("asset", kit_id=row["kit_id"], asset_id=asset_id)
    return asset_public(_asset_row(asset_id))


def delete_asset(asset_id: int) -> None:
    row = _asset_row(asset_id)
    db.delete("brand_assets", asset_id)
    _touch(row["kit_id"])
    drop_own_file(row["file_id"], SOURCE_ASSET)
    publish("asset_deleted", kit_id=row["kit_id"], asset_id=asset_id)


def reorder_assets(kit_id: int, asset_ids: list[int]) -> list[dict]:
    """Set the order of the given assets (usually all of one kind) as listed."""
    _kit_row(kit_id)
    own = {r["id"] for r in db.fetch_all("SELECT id FROM brand_assets WHERE kit_id = ?", (kit_id,))}
    unknown = [i for i in asset_ids if i not in own]
    if unknown:
        raise AppError("bad_order", 400, "These items are not in this kit", ids=unknown)
    with db.tx():
        for index, asset_id in enumerate(asset_ids):
            db.update("brand_assets", asset_id, {"sort": index + 1})
    _touch(kit_id)
    publish("asset_order", kit_id=kit_id)
    return [asset_public(a) for a in _assets(kit_id)]


# ── snapshot for works (studio 04, chat 15) ────────────────────────────────


def snapshot_kit(kit_id: int) -> dict:
    """Everything a work needs from a kit, copied: later kit edits do not change the work.

    Shape::

        {"kit_id", "name", "version" (kit revision), "taken_at",
         "colors": [{"hex", "label"}], "tone",
         "fonts": [{"name", "family", "category", "source", "google_family", "file_id", "note"}],
         "logos": [{"file_id", "name", "position_hint", "note"}],
         "elements": [{"kind", "file_id", "name", "position_hint", "note"}],   # frame … other
         "references": [{"file_id", "name", "note"}]}

    The file ids stay valid while the kit keeps them; a work that keeps the
    snapshot after the kit dropped a file should register its own
    ``files.usage_provider`` for those ids.
    """
    kit = _kit_row(kit_id)
    snap: dict[str, Any] = {
        "kit_id": kit["id"], "name": kit["name"], "version": kit["revision"], "taken_at": db.now(),
        "colors": kit["colors_json"] or [], "tone": kit["tone"],
        "fonts": [], "logos": [], "elements": [], "references": [],
    }
    for a in _assets(kit_id):
        if a["kind"] == "font":
            snap["fonts"].append({"name": a["name"], "family": a["font_family"], "category": a["font_category"],
                                  "source": a["font_source"], "google_family": a["google_family"],
                                  "file_id": a["file_id"], "note": a["note"]})
        elif a["kind"] == "logo":
            snap["logos"].append({"file_id": a["file_id"], "name": a["name"],
                                  "position_hint": a["position_hint"], "note": a["note"]})
        elif a["kind"] == "reference":
            snap["references"].append({"file_id": a["file_id"], "name": a["name"], "note": a["note"]})
        else:
            snap["elements"].append({"kind": a["kind"], "file_id": a["file_id"], "name": a["name"],
                                     "position_hint": a["position_hint"], "note": a["note"]})
    return snap


def kit_changed(snapshot: dict | None) -> bool | None:
    """True when the kit was edited after the snapshot; None when the kit is gone."""
    if not snapshot or not snapshot.get("kit_id"):
        return None
    row = db.get("brand_kits", int(snapshot["kit_id"]))
    if row is None:
        return None
    return row["revision"] != snapshot.get("version")


# ── file usage: a picture or font in a kit cannot be deleted from the media library ──


@files.usage_provider
def _kit_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT DISTINCT k.id, k.name FROM brand_assets a JOIN brand_kits k ON k.id = a.kit_id WHERE a.file_id = ?",
        (file_id,))
    return [{"type": "brand_kit", "id": r["id"], "title": r["name"]} for r in rows]
