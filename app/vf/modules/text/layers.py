"""The words and the canvas layers of a design, checked and brought to one shape.

Boxes are fractions of the picture (0..1), so a layer keeps its place when the
background changes size. Three kinds of layer:

* text  — ``{id, type: "text", block_id, role, text, font: {file_id, family} | None, size,
  font_size, color, align, vertical, bold, uppercase, line_height, scrim, shadow, x, y, w, h,
  visible, opacity}``; ``font_size`` is a share of the picture height (None = by ``size``),
  the words shrink until they fit the box; ``font`` None = the bundled Roboto;
* logo  — ``{id, type: "logo", file_id (None = the kit's first logo), x, y, w, h, visible, opacity}``;
* shape — ``{id, type: "shape", shape: rect|ellipse, fill, radius (share of the short side),
  x, y, w, h, visible, opacity}``.

The words of a design (``texts``): ``[{id, role, text, size, locked}]``. A text layer
with a ``block_id`` shows the words of that block.
"""

from __future__ import annotations

import re
from typing import Any

from vf.core.errors import AppError
from vf.modules.text import common as C

_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MIN_SIDE = 0.02


def _num(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return round(max(low, min(high, number)), 4)


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _int_or_none(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def box(raw: dict, default: tuple[float, float, float, float] = (0.06, 0.66, 0.88, 0.28)) -> dict:
    """``{x, y, w, h}`` kept inside the picture."""
    w = _num(raw.get("w"), default[2], MIN_SIDE, 1.0)
    h = _num(raw.get("h"), default[3], MIN_SIDE, 1.0)
    x = _num(raw.get("x"), default[0], 0.0, 1.0 - w)
    y = _num(raw.get("y"), default[1], 0.0, 1.0 - h)
    return {"x": x, "y": y, "w": w, "h": h}


def role(value: Any) -> str:
    return _choice(value, C.TEXT_ROLES, "body")


def size(value: Any, role_name: str = "body") -> str:
    return _choice(value, C.SIZES, C.DEFAULT_SIZE.get(role_name, "md"))


def _font(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    file_id = _int_or_none(value.get("file_id"))
    family = C.clean_line(value.get("family"), 120)
    if not file_id and not family:
        return None
    return {"file_id": file_id, "family": family}


def _layer_id(value: Any, index: int, taken: set[str]) -> str:
    text = str(value or "")
    if not _ID.match(text) or text in taken:
        text = f"l{index + 1}"
        n = index + 1
        while text in taken:
            n += 1
            text = f"l{n}"
    taken.add(text)
    return text


def text_layer(raw: dict, layer_id: str) -> dict:
    role_name = role(raw.get("role"))
    font_size = raw.get("font_size")
    return {
        "id": layer_id, "type": "text",
        "block_id": C.clean_line(raw.get("block_id"), 40) or None,
        "role": role_name,
        "text": C.clean_block(raw.get("text"), C.MAX_TEXT),
        "font": _font(raw.get("font")),
        "size": size(raw.get("size"), role_name),
        "font_size": None if font_size in (None, "") else _num(font_size, 0.045, 0.012, 0.3),
        "color": C.hex_color(raw.get("color"), "#FFFFFF"),
        "align": _choice(raw.get("align"), C.ALIGNS, "center"),
        "vertical": _choice(raw.get("vertical"), C.VERTICALS, "middle"),
        "bold": _bool(raw.get("bold"), role_name == "headline"),
        "uppercase": _bool(raw.get("uppercase"), False),
        "line_height": _num(raw.get("line_height"), 1.28, 0.8, 2.5),
        "scrim": _bool(raw.get("scrim"), False),
        "shadow": _bool(raw.get("shadow"), False),
        **box(raw),
        "visible": _bool(raw.get("visible"), True),
        "opacity": _num(raw.get("opacity"), 1.0, 0.0, 1.0),
    }


def logo_layer(raw: dict, layer_id: str) -> dict:
    return {
        "id": layer_id, "type": "logo",
        "file_id": _int_or_none(raw.get("file_id")),
        **box(raw, (0.78, 0.86, 0.16, 0.1)),
        "visible": _bool(raw.get("visible"), True),
        "opacity": _num(raw.get("opacity"), 1.0, 0.0, 1.0),
    }


def shape_layer(raw: dict, layer_id: str) -> dict:
    return {
        "id": layer_id, "type": "shape",
        "shape": _choice(raw.get("shape"), C.SHAPES, "rect"),
        "fill": C.hex_color(raw.get("fill"), "#111111"),
        "radius": _num(raw.get("radius"), 0.0, 0.0, 0.5),
        **box(raw, (0.1, 0.7, 0.8, 0.2)),
        "visible": _bool(raw.get("visible"), True),
        "opacity": _num(raw.get("opacity"), 1.0, 0.0, 1.0),
    }


def normalize_layers(value: Any) -> list[dict]:
    """The layers as sent by the editor (bottom first); unknown kinds are an error."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "Layers are a list")
    if len(value) > C.MAX_LAYERS:
        raise AppError("too_many_layers", 400, "Too many layers", max=C.MAX_LAYERS)
    out: list[dict] = []
    taken: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise AppError("bad_request", 400, "A layer is an object")
        kind = raw.get("type")
        layer_id = _layer_id(raw.get("id"), index, taken)
        if kind == "text":
            out.append(text_layer(raw, layer_id))
        elif kind == "logo":
            out.append(logo_layer(raw, layer_id))
        elif kind == "shape":
            out.append(shape_layer(raw, layer_id))
        else:
            raise AppError("bad_layer", 400, "Unknown layer kind", kind=str(kind))
    return out


def normalize_texts(value: Any) -> list[dict]:
    """``[{id, role, text, size, locked}]``: at most 8 blocks of 600 characters."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "The words are a list")
    if len(value) > C.MAX_TEXTS:
        raise AppError("too_many_texts", 400, "Too many blocks of words", max=C.MAX_TEXTS)
    out: list[dict] = []
    taken: set[str] = set()
    for index, raw in enumerate(value):
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            raise AppError("bad_request", 400, "A block of words is an object")
        role_name = role(raw.get("role"))
        text_id = str(raw.get("id") or "")
        if not _ID.match(text_id) or text_id in taken:
            text_id = f"t{index + 1}"
            n = index + 1
            while text_id in taken:
                n += 1
                text_id = f"t{n}"
        taken.add(text_id)
        out.append({"id": text_id, "role": role_name, "text": C.clean_block(raw.get("text"), C.MAX_TEXT),
                    "size": size(raw.get("size"), role_name), "locked": _bool(raw.get("locked"), False)})
    return out


def texts_from_frame(blocks: Any) -> list[dict]:
    """The frame's words (studio ``text_blocks_json``: ``[{role, text}]``) as design texts."""
    items = [b for b in (blocks or []) if isinstance(b, dict) and str(b.get("text") or "").strip()]
    return normalize_texts([{"role": b.get("role"), "text": b.get("text"), "size": b.get("size")}
                            for b in items[:C.MAX_TEXTS]])


def bind_texts(layers: list[dict], texts: list[dict]) -> list[dict]:
    """Text layers tied to a block (``block_id``) take that block's words and role."""
    by_id = {t["id"]: t for t in texts}
    out = []
    for layer in layers:
        if layer["type"] == "text" and layer.get("block_id"):
            block = by_id.get(layer["block_id"])
            if block is None:
                layer = {**layer, "block_id": None}
            else:
                layer = {**layer, "text": block["text"], "role": block["role"]}
        out.append(layer)
    return out


def from_layout(layout_layers: list[dict], texts: list[dict]) -> list[dict]:
    """A ready layout filled with the design's words: by role first, then in reading order.

    Text layers left without words are dropped; words left without a layer are not placed
    (the person adds a layer for them)."""
    raw = normalize_layers([{**layer, "id": None} for layer in layout_layers])
    text_slots = [i for i, layer in enumerate(raw) if layer["type"] == "text"]
    free = [t for t in texts if t["text"]]
    assigned: dict[int, dict] = {}
    for i in text_slots:
        match = next((t for t in free if t["role"] == raw[i]["role"]), None)
        if match is not None:
            assigned[i] = match
            free.remove(match)
    for i in text_slots:
        if i not in assigned and free:
            assigned[i] = free.pop(0)
    out = []
    for i, layer in enumerate(raw):
        if layer["type"] == "text":
            block = assigned.get(i)
            if block is None:
                continue
            # the layout's size stays: its boxes are drawn for it
            layer = {**layer, "block_id": block["id"], "text": block["text"], "role": block["role"]}
        out.append(layer)
    return out


__all__ = ["bind_texts", "box", "from_layout", "normalize_layers", "normalize_texts", "texts_from_frame"]
