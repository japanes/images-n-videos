"""Ready layouts of the editor: a set of layers dropped onto the picture in one press.

Built-in rows come with the migration and have a ``code`` (their name lives in the locale
``text.layouts.<code>``); the person can keep the current layers as a layout of their own.
Boxes are fractions of the picture, so a layout fits any aspect ratio."""

from __future__ import annotations

from typing import Any

from vf.core import db
from vf.core.errors import AppError, NotFound
from vf.modules.text import common as C
from vf.modules.text import layers as L


def public(row: dict) -> dict:
    layers = row.get("layers_json") or []
    return {"id": row["id"], "code": row.get("code"), "title": row.get("title") or "",
            "builtin": bool(row.get("builtin")), "layers": layers,
            "texts": sum(1 for layer in layers if layer.get("type") == "text")}


def layout_row(layout_id: Any) -> dict:
    try:
        number = int(layout_id)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "A layout id is expected") from None
    row = db.get("editor_layouts", number)
    if row is None:
        raise NotFound("layout", id=layout_id)
    return row


def list_layouts() -> list[dict]:
    rows = db.fetch_all("SELECT * FROM editor_layouts ORDER BY builtin DESC, sort, id")
    return [public(r) for r in rows]


def _template(layers: list[dict]) -> list[dict]:
    """The design's layers as a layout: no words, no ties to a block, no ids."""
    out = []
    for layer in layers:
        item = {k: v for k, v in layer.items() if k not in ("id", "text", "block_id")}
        out.append(item)
    return out


def create(body: Any) -> dict:
    """``{title, layers}``: the person's own layout (the words are not kept, only the boxes)."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    title = C.clean_line(body.get("title"), C.MAX_LAYOUT_TITLE)
    if not title:
        raise AppError("bad_request", 400, "A layout needs a name")
    layers = L.normalize_layers(body.get("layers"))
    if not layers:
        raise AppError("empty_layout", 400, "There are no layers to keep")
    own = db.fetch_value("SELECT COUNT(*) FROM editor_layouts WHERE builtin = 0", (), 0)
    if own >= C.MAX_LAYOUTS:
        raise AppError("too_many_layouts", 409, "Too many layouts of your own", max=C.MAX_LAYOUTS)
    now = db.now()
    sort = db.fetch_value("SELECT COALESCE(MAX(sort), 0) FROM editor_layouts", (), 0) + 10
    layout_id = db.insert("editor_layouts", {"code": None, "title": title, "layers_json": _template(layers),
                                             "builtin": 0, "sort": sort, "created_at": now, "updated_at": now})
    return public(layout_row(layout_id))


def delete(layout_id: Any) -> None:
    row = layout_row(layout_id)
    if row.get("builtin"):
        raise AppError("builtin_layout", 409, "A built-in layout cannot be deleted")
    db.delete("editor_layouts", row["id"])


__all__ = ["create", "delete", "layout_row", "list_layouts", "public"]
