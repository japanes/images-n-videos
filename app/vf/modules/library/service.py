"""Styles and photo styles: lookup for the studio and the chat, own styles, previews.

Built-in rows come from the seed (``seed.sync``) and are read-only; own rows
(``code IS NULL``) are made here. A brief keeps a reference to a style and the
text is put together by ``render_style`` when the prompt is assembled.
"""

from __future__ import annotations

import io
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from vf.core import db, events, files, google
from vf.core.errors import AppError, NotFound
from vf.modules.library import seed
from vf.modules.library import variables as V

log = logging.getLogger("vf.library")

KINDS = seed.KINDS
TABS = ("all", "builtin", "mine")
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 1000
MAX_PROMPT_CHARS = V.MAX_STYLE_CHARS
MAX_QUERY_CHARS = 200
PREVIEW_MIMES = ("image/png", "image/jpeg", "image/webp")
MAX_PREVIEW_BYTES = 20 * 1024 * 1024
SOURCE_PREVIEW = "preset"            # files.source_type of an uploaded preview
USAGE_TYPE = "style"                 # what the media library says uses a preview


# ── categories ──────────────────────────────────────────────────────────────

def _category_rows() -> dict[str, dict]:
    rows = db.fetch_all("SELECT slug, parent, depth, sort, title, title_uk, title_en, removed_from_seed "
                        "FROM preset_categories ORDER BY depth, sort, slug")
    return {r["slug"]: r for r in rows}


def _category_short(row: dict) -> dict:
    return {"slug": row["slug"], "title": row["title"], "title_uk": row["title_uk"], "title_en": row["title_en"]}


def category_path(slug: str | None, cats: dict[str, dict] | None = None) -> list[dict]:
    """Root-first chain of a category: ``[{slug, title, title_uk, title_en}]``."""
    cats = _category_rows() if cats is None else cats
    out: list[dict] = []
    cur = slug
    while cur and cur in cats and len(out) < 10:
        out.append(_category_short(cats[cur]))
        cur = cats[cur]["parent"]
    return list(reversed(out))


def _scope(tab: str = "all", kind: str | None = None) -> tuple[list[str], list[Any]]:
    if tab not in TABS:
        raise AppError("validation", 422, f"tab must be one of {', '.join(TABS)}", field="tab")
    where: list[str] = []
    params: list[Any] = []
    if tab == "builtin":
        where.append("is_builtin = 1 AND removed_from_seed = 0")
    elif tab == "mine":
        where.append("is_builtin = 0")
    else:
        where.append("(is_builtin = 0 OR removed_from_seed = 0)")
    if kind:
        if kind not in KINDS:
            raise AppError("validation", 422, f"kind must be one of {', '.join(KINDS)}", field="kind")
        where.append("kind = ?")
        params.append(kind)
    return where, params


def _ancestors(slug: str, cats: dict[str, dict]) -> list[str]:
    out = []
    cur: str | None = slug
    while cur and len(out) < 10:
        out.append(cur)
        cur = cats[cur]["parent"] if cur in cats else (cur.rsplit("/", 1)[0] if "/" in cur else None)
    return out


def category_tree(*, tab: str = "all", kind: str | None = None) -> dict:
    """Every category (flat, ``parent`` links) with how many styles of the filter sit in its subtree."""
    cats = _category_rows()
    where, params = _scope(tab, kind)
    direct = db.fetch_all(f"SELECT category, COUNT(*) AS n FROM presets WHERE {' AND '.join(where)} "
                          "GROUP BY category", params)
    counts: dict[str, int] = defaultdict(int)
    total = 0
    uncategorized = 0
    for r in direct:
        total += r["n"]
        if not r["category"] or r["category"] not in cats:
            uncategorized += r["n"]
            continue
        for slug in _ancestors(r["category"], cats):
            counts[slug] += r["n"]
    items = [{**_category_short(c), "parent": c["parent"], "depth": c["depth"], "sort": c["sort"],
              "count": counts.get(slug, 0)}
             for slug, c in cats.items() if not c["removed_from_seed"] or counts.get(slug)]
    return {"items": items, "total": total, "uncategorized": uncategorized}


def category_exists(slug: str) -> bool:
    return db.fetch_value("SELECT 1 FROM preset_categories WHERE slug = ?", (slug,)) is not None


# ── reading styles ──────────────────────────────────────────────────────────

def _seed_preview(row: dict) -> Path | None:
    return seed.preview_path(row.get("preview_seed"))


def _preview_urls(row: dict) -> tuple[str | None, str | None]:
    if row.get("preview_file_id"):
        return files.url(row["preview_file_id"], w=480), files.url(row["preview_file_id"])
    if _seed_preview(row):
        u = f"/api/library/previews/{row['id']}"
        return u, u
    return None, None


def public(row: dict, cats: dict[str, dict] | None = None) -> dict:
    """What the browser and other modules get about a style."""
    zones = row.get("text_zones_json")
    zones = zones if isinstance(zones, dict) else None
    thumb, full = _preview_urls(row)
    return {
        "id": row["id"], "code": row["code"], "kind": row["kind"], "title": row["title"],
        "description": row["description"] or "", "prompt": row["prompt"],
        "variables": V.extract_variables(row["prompt"]),
        "text_zones": zones, "text_zone_count": V.count_text_zones(zones),
        "category": row["category"], "category_path": category_path(row["category"], cats),
        "is_builtin": bool(row["is_builtin"]), "removed": bool(row["removed_from_seed"]),
        "preview_url": thumb, "preview_full_url": full, "preview_file_id": row["preview_file_id"],
        "copied_from": row["copied_from"], "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _row(style: int | str) -> dict:
    if isinstance(style, str) and not style.strip().isdigit():
        row = db.fetch_one("SELECT * FROM presets WHERE code = ?", (style.strip(),))
    else:
        row = db.get("presets", int(style))
    if row is None:
        raise NotFound("style", id=style)
    return row


def get_style(style: int | str) -> dict:
    """One style by id or by built-in code (``"style-14"``). Raises ``not_found``."""
    return public(_row(style))


def find_style(style: int | str | None) -> dict | None:
    """Like ``get_style`` but None when it is gone (a deleted own style, a bad id)."""
    if style is None or style == "":
        return None
    try:
        return get_style(style)
    except (NotFound, ValueError, TypeError):
        return None


def _fold(text: Any) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _matches(row: dict, words: list[str], cats: dict[str, dict]) -> bool:
    path = category_path(row["category"], cats)
    hay = _fold(" ".join([
        row["title"] or "", row["description"] or "", row["prompt"] or "", row["code"] or "",
        *[" ".join(filter(None, (c["title"], c["title_uk"], c["title_en"]))) for c in path],
    ]))
    return all(w in hay for w in words)


def list_styles(*, tab: str = "all", kind: str | None = None, category: str | None = None, q: str | None = None,
                limit: int = 48, offset: int = 0) -> dict:
    """The picker and the library screen: filter, search, a page.

    ``category`` takes its whole subtree. ``q`` looks in the title, description,
    style text and category names, every word must be found (any case).
    Order: own styles (newest first), then built-ins in library order.
    """
    where, params = _scope(tab, kind)
    if category:
        where.append("(category = ? OR substr(category, 1, ?) = ?)")
        params += [category, len(category) + 1, category + "/"]
    rows = db.fetch_all(
        f"SELECT * FROM presets WHERE {' AND '.join(where)} "
        "ORDER BY is_builtin, CASE WHEN is_builtin = 0 THEN updated_at END DESC, sort, id", params)
    cats = _category_rows()
    words = _fold(str(q or "")[:MAX_QUERY_CHARS]).split()
    if words:
        rows = [r for r in rows if _matches(r, words, cats)]
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    return {"items": [public(r, cats) for r in rows[offset:offset + limit]], "total": len(rows),
            "limit": limit, "offset": offset}


def random_style(*, kind: str = "style", tab: str = "all", category: str | None = None,
                 exclude: int | None = None) -> dict | None:
    """The dice next to the chat input: any style of the filter, not the one just shown."""
    where, params = _scope(tab, kind)
    if category:
        where.append("(category = ? OR substr(category, 1, ?) = ?)")
        params += [category, len(category) + 1, category + "/"]
    ids = [r["id"] for r in db.fetch_all(f"SELECT id FROM presets WHERE {' AND '.join(where)}", params)]
    if exclude is not None and len(ids) > 1:
        ids = [i for i in ids if i != exclude]
    return get_style(random.choice(ids)) if ids else None


# ── putting the text together ───────────────────────────────────────────────

def render_style(style: Any, values: dict | list | None = None, extra: str | None = None) -> dict | None:
    """The real style text for a prompt.

    ``style`` is an id, a built-in code or a reference from a brief (dict or the
    JSON string ``{"preset": 42, "vars": [...], "extra": "..."}``). ``values`` fill
    the slots (over the ones in the reference); a blank slot takes its default.
    ``extra`` (or the reference's) is the person's own words, added on a new line.

    Returns ``{preset_id, code, kind, title, prompt, text_zones, values, extra, preview_url}``
    or None when the style is gone — the work is then made without a style.
    """
    ref = None
    if isinstance(style, dict) or V.is_style_ref(style):
        ref = V.parse_style_ref(style)
        if ref is None:
            return None
        style = ref["preset"]
    if isinstance(style, bool) or style is None or style == "":
        return None
    try:
        row = _row(style)
    except (NotFound, ValueError, TypeError):
        return None
    typed = {v["key"]: v["value"] for v in (ref or {}).get("vars", [])}
    typed.update(V.clean_values(values))
    extra_text = (ref or {}).get("extra", "") if extra is None else extra
    extra_text = str(extra_text or "")[:V.MAX_EXTRA_CHARS].strip()
    filled = V.fill_variables(row["prompt"], typed)
    text = "\n".join(part for part in (filled, extra_text) if part).strip()[:V.MAX_STYLE_CHARS].strip()
    if not text:
        return None
    zones = row.get("text_zones_json")
    return {
        "preset_id": row["id"], "code": row["code"], "kind": row["kind"], "title": row["title"],
        "prompt": text, "text_zones": zones if isinstance(zones, dict) else None,
        "values": {v["key"]: typed.get(v["key"], "") for v in V.extract_variables(row["prompt"])},
        "extra": extra_text, "preview_url": _preview_urls(row)[0],
    }


def resolve_style_value(value: Any) -> dict | None:
    """A brief's style field as stored: a reference -> ``render_style``; plain words the
    person typed -> those words (trimmed, capped). Empty -> None."""
    if isinstance(value, dict) or V.is_style_ref(value):
        return render_style(value)
    text = str(value or "").strip()[:V.MAX_STYLE_CHARS].strip()
    if not text:
        return None
    return {"preset_id": None, "code": None, "kind": "style", "title": None, "prompt": text,
            "text_zones": None, "values": {}, "extra": "", "preview_url": None}


def photo_style_text(style: int | str | None) -> str | None:
    """Wording of a photo style (the studio stores its id). Gone -> None: a plain photo."""
    if style is None or style == "":
        return None
    try:
        row = _row(style)
    except (NotFound, ValueError, TypeError):
        return None
    if row["kind"] != "photo_style":
        return None
    return V.fill_variables(row["prompt"]) or None


def preview_blob(style: int | str) -> google.Blob | None:
    """The style's preview as a picture for the model, or None. Send it only when the
    person turned on "show the model the style example" (nothing implicit)."""
    try:
        row = _row(style)
    except (NotFound, ValueError, TypeError):
        return None
    if row.get("preview_file_id"):
        try:
            return google.blob_from_file(row["preview_file_id"])
        except (AppError, OSError):
            return None
    p = _seed_preview(row)
    if p is None:
        return None
    data = p.read_bytes()
    return google.Blob(data, files.guess_mime(p.name, data))


# ── own styles ──────────────────────────────────────────────────────────────

def _too_long(field: str, limit: int) -> AppError:
    return AppError("library_too_long", 422, f"{field} is longer than {limit} characters", field=field, max=limit)


def _validated(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "title" in data or not partial:
        title = " ".join(str(data.get("title") or "").split())
        if not title:
            raise AppError("library_title_required", 422, "The style needs a name", field="title")
        if len(title) > MAX_TITLE_CHARS:
            raise _too_long("title", MAX_TITLE_CHARS)
        out["title"] = title
    if "kind" in data or not partial:
        kind = str(data.get("kind") or "style")
        if kind not in KINDS:
            raise AppError("library_bad_kind", 422, f"kind must be one of {', '.join(KINDS)}", field="kind")
        out["kind"] = kind
    if "description" in data or not partial:
        description = str(data.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise _too_long("description", MAX_DESCRIPTION_CHARS)
        out["description"] = description
    if "prompt" in data or not partial:
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            raise AppError("library_prompt_required", 422, "The style needs its text", field="prompt")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise _too_long("prompt", MAX_PROMPT_CHARS)
        keys = {V.variable_key(m.group(1)) for m in V.VARIABLE_RE.finditer(prompt)}
        if len(keys) > V.MAX_PROMPT_VARIABLES:
            raise AppError("library_too_many_variables", 422, "Too many {{fields}} in the style text",
                           field="prompt", max=V.MAX_PROMPT_VARIABLES, count=len(keys))
        out["prompt"] = prompt
    if "category" in data or not partial:
        category = str(data.get("category") or "").strip() or None
        if category and not category_exists(category):
            raise AppError("library_unknown_category", 422, "There is no such category", field="category")
        out["category"] = category
    if "text_zones" in data:
        out["text_zones_json"] = V.parse_text_zones(data.get("text_zones"))
    return out


def _own_row(style_id: int) -> dict:
    row = _row(int(style_id))
    if row["is_builtin"]:
        raise AppError("library_builtin_readonly", 409,
                       "Built-in styles cannot be changed. Copy it to “My styles” first.", id=row["id"])
    return row


def _publish(action: str, style_id: int) -> None:
    events.publish("library.updated", {"action": action, "id": style_id})


def create_style(data: dict[str, Any]) -> dict:
    """A new own style: ``{title, prompt, kind?, description?, category?, text_zones?}``."""
    values = _validated(data, partial=False)
    values.setdefault("text_zones_json", None)
    now = db.now()
    style_id = db.insert("presets", {"code": None, **values, "is_builtin": 0, "removed_from_seed": 0,
                                     "sort": 0, "created_at": now, "updated_at": now})
    _publish("created", style_id)
    return get_style(style_id)


def update_style(style_id: int, data: dict[str, Any]) -> dict:
    """Change an own style; only the fields given change. ``text_zones: null`` clears the map."""
    row = _own_row(style_id)
    values = _validated(data, partial=True)
    if values:
        db.update("presets", row["id"], {**values, "updated_at": db.now()})
        _publish("updated", row["id"])
    return get_style(row["id"])


def delete_style(style_id: int) -> dict:
    """Delete an own style. An uploaded preview stays in the media library.
    Works that referenced the style are made without it from now on."""
    row = _own_row(style_id)
    db.delete("presets", row["id"])
    _publish("deleted", row["id"])
    return {"ok": True, "id": row["id"], "preview_file_id": row["preview_file_id"]}


def copy_style(style_id: int, title: str | None = None) -> dict:
    """A copy in "My styles" (built-in or own) — the way to change a built-in."""
    row = _row(int(style_id))
    now = db.now()
    new_title = " ".join(str(title or "").split()) or row["title"]
    if len(new_title) > MAX_TITLE_CHARS:
        raise _too_long("title", MAX_TITLE_CHARS)
    zones = row.get("text_zones_json")
    new_id = db.insert("presets", {
        "code": None, "kind": row["kind"], "title": new_title, "description": row["description"] or "",
        "prompt": row["prompt"], "text_zones_json": zones if isinstance(zones, dict) else None,
        "category": row["category"], "is_builtin": 0, "removed_from_seed": 0, "sort": 0,
        # the copy shows the same picture: a shipped one is shared, an uploaded one is referenced
        "preview_seed": row["preview_seed"], "preview_file_id": row["preview_file_id"],
        "copied_from": row["code"] or row["copied_from"], "created_at": now, "updated_at": now,
    })
    _publish("created", new_id)
    return get_style(new_id)


def check_preview(data: bytes, name: str | None = None) -> str:
    """Mime of an uploaded preview, or a clear error."""
    if not data:
        raise AppError("empty_file", 400, "The file is empty")
    if len(data) > MAX_PREVIEW_BYTES:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=MAX_PREVIEW_BYTES // 1024 // 1024)
    mime = files.sniff_mime(data[:32])
    if mime not in PREVIEW_MIMES:
        raise AppError("library_bad_image", 400, "Only PNG, JPEG and WebP pictures are supported", name=name)
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as exc:  # noqa: BLE001
        raise AppError("library_bad_image", 400, "The picture could not be read", name=name) from exc
    return mime


def set_preview(style_id: int, data: bytes, name: str | None = None) -> dict:
    """Upload a preview for an own style. The file joins the media library; a replaced
    preview stays there too."""
    row = _own_row(style_id)
    mime = check_preview(data, name)
    saved = files.save_bytes(data, mime=mime, name=name or f"style-{row['id']}", origin="upload",
                             title=row["title"], source_type=SOURCE_PREVIEW, source_id=row["id"])
    db.update("presets", row["id"], {"preview_file_id": saved["id"], "preview_seed": None, "updated_at": db.now()})
    _publish("updated", row["id"])
    return get_style(row["id"])


def set_preview_file(style_id: int, file_id: int) -> dict:
    """Use a picture already in the media library (a generated frame) as the preview."""
    row = _own_row(style_id)
    f = files.get(int(file_id))
    if f["mime"] not in PREVIEW_MIMES:
        raise AppError("library_bad_image", 400, "Only PNG, JPEG and WebP pictures are supported", id=file_id)
    db.update("presets", row["id"], {"preview_file_id": f["id"], "preview_seed": None, "updated_at": db.now()})
    _publish("updated", row["id"])
    return get_style(row["id"])


def remove_preview(style_id: int) -> dict:
    """Unlink the preview of an own style (the file itself stays in the media library)."""
    row = _own_row(style_id)
    db.update("presets", row["id"], {"preview_file_id": None, "preview_seed": None, "updated_at": db.now()})
    _publish("updated", row["id"])
    return get_style(row["id"])


def seed_preview_file(style_id: int) -> Path:
    """Path of a shipped preview for ``GET /api/library/previews/{id}``."""
    row = _row(int(style_id))
    p = _seed_preview(row)
    if p is None:
        raise NotFound("preview", id=style_id)
    return p


# ── file usage: the media library will not delete a preview a style shows ────


@files.usage_provider
def _preview_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all("SELECT id, title FROM presets WHERE preview_file_id = ?", (file_id,))
    return [{"type": USAGE_TYPE, "id": r["id"], "title": r["title"]} for r in rows]
