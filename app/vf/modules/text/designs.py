"""A design: one opening of «Text on image» on a studio frame.

``open_design`` finds or makes the design for the picture the person clicked in the chat:

1. that picture was saved by this tool  → the design (or a copy of that save's layers);
2. a draft on that picture exists       → the draft;
3. otherwise                            → a new draft: the picture is the background, the words
   are the frame's text blocks, no layers yet.

«Save» draws the layers with Pillow over the background and puts the result into the frame as
a new version (source «editor»). The frame keeps the clean background (``clean_file_id``) and the
layers (``text_layers_json``); the chat posts the new picture when the tool closes.
"""

from __future__ import annotations

import json
from typing import Any

from vf.core import db, files, settings
from vf.core.errors import AppError, NotFound
from vf.modules import brand, studio
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_TEXT_BLOCKS
from vf.modules.text import common as C
from vf.modules.text import fonts as F
from vf.modules.text import layers as L
from vf.modules.text import placement as P
from vf.modules.text import render as R
from vf.modules.text import store as S

PLACEMENT_SIDE = 1024  # the picture the free steps look at (colours under a zone)
MAX_OPTIONS = 40


# ── opening ─────────────────────────────────────────────────────────────────

def _image_row(file_id: int) -> dict:
    row = files.get(int(file_id))
    if row["kind"] != "image":
        raise AppError("not_an_image", 400, "The file is not a picture", file_id=file_id)
    return row


def _size_of(row: dict) -> tuple[int, int]:
    width, height = row.get("width") or 0, row.get("height") or 0
    if not (width and height):
        try:
            img = R.open_background(files.read_bytes(row["id"]))
            width, height = img.size
        except AppError:
            width, height = 0, 0
    return int(width), int(height)


def _chat_ids(body: dict) -> tuple[int | None, int | None]:
    chat_id = S.int_or_none(body.get("chat_id"))
    message_id = S.int_or_none(body.get("message_id"))
    if chat_id and db.get("chats", chat_id) is None:
        chat_id = None
    if message_id and db.get("chat_messages", message_id) is None:
        message_id = None
    return chat_id, message_id


def _default_options() -> dict:
    return {"language": C.language(settings.get("general.text_language", C.DEFAULT_LANGUAGE))}


def _create(frame: dict, background_id: int, *, texts: list[dict], layers: list[dict], chat_id: int | None,
            message_id: int | None) -> int:
    work = W.work_row(frame["work_id"])
    width, height = _size_of(_image_row(background_id))
    now = db.now()
    return db.insert("text_designs", {
        "frame_id": frame["id"], "chat_id": chat_id, "message_id": message_id, "kit_id": work.get("kit_id"),
        "background_file_id": background_id, "width": width, "height": height,
        "texts_json": texts, "layers_json": L.bind_texts(layers, texts), "options_json": _default_options(),
        "status": "draft", "created_at": now, "updated_at": now,
    })


def _attach(design: dict, chat_id: int | None, message_id: int | None) -> int:
    """The latest opening decides where the journal points (chat, message)."""
    values = {}
    if chat_id and chat_id != design.get("chat_id"):
        values["chat_id"] = chat_id
    if message_id and message_id != design.get("message_id"):
        values["message_id"] = message_id
    if values:
        S.update(design["id"], values)
    return design["id"]


def open_design(body: Any) -> dict:
    """``{frame_id, file_id?, chat_id?, message_id?}`` → the design view."""
    body = body if isinstance(body, dict) else {}
    frame_id = S.int_or_none(body.get("frame_id"))
    if not frame_id:
        raise AppError("bad_request", 400, "frame_id is expected")
    frame = W.frame_row(frame_id)
    file_id = S.int_or_none(body.get("file_id")) or frame.get("file_id")
    if not file_id:
        raise AppError("no_picture", 409, "The frame has no picture yet")
    _image_row(file_id)
    chat_id, message_id = _chat_ids(body)

    saved = db.fetch_one("SELECT * FROM text_saves WHERE file_id = ? AND frame_id = ? ORDER BY id DESC LIMIT 1",
                         (file_id, frame_id))
    if saved is not None:
        design = db.get("text_designs", saved["design_id"])
        if design is not None and design.get("result_file_id") == file_id:
            return view(_attach(design, chat_id, message_id))
        background = saved.get("background_file_id") or file_id
        texts = L.normalize_texts(saved.get("texts_json") or [])
        layers = L.normalize_layers(saved.get("layers_json") or [])
        return view(_create(frame, background, texts=texts, layers=layers, chat_id=chat_id, message_id=message_id))

    draft = db.fetch_one("SELECT * FROM text_designs WHERE frame_id = ? AND background_file_id = ? AND status = 'draft'"
                         " ORDER BY id DESC LIMIT 1", (frame_id, file_id))
    if draft is not None:
        return view(_attach(draft, chat_id, message_id))

    texts = L.texts_from_frame(frame.get("text_blocks_json"))
    return view(_create(frame, file_id, texts=texts, layers=[], chat_id=chat_id, message_id=message_id))


# ── the view ────────────────────────────────────────────────────────────────

def _file_brief(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    try:
        row = files.get(file_id)
    except NotFound:
        return None
    return {"file_id": row["id"], "url": files.url(row["id"]), "thumb_url": files.url(row["id"], w=480),
            "width": row.get("width"), "height": row.get("height")}


def _kits() -> list[dict]:
    return [{"id": k["id"], "name": k["name"]} for k in brand.list_kits()]


def logo_of(design: dict, snap: dict | None) -> int | None:
    logos = F.kit_logos(design.get("kit_id"), snap)
    return logos[0]["file_id"] if logos else None


def view(design_id: int) -> dict:
    from vf.modules.text import backgrounds as B  # backgrounds import this module

    design = S.design_row(design_id)
    frame = S.frame_of(design)
    work = S.work_of(frame)
    snap = S.snapshot_for(design, work)
    kit_id = design.get("kit_id")
    count = db.fetch_value("SELECT COUNT(*) FROM frames WHERE work_id = ?", (frame["work_id"],), 0)
    return {
        "id": design["id"], "frame_id": frame["id"], "work_id": frame["work_id"],
        "chat_id": design.get("chat_id"), "message_id": design.get("message_id"),
        "kit_id": kit_id, "status": design["status"], "cost_usd": round(design.get("cost_usd") or 0, 6),
        "saved_at": design.get("saved_at"), "created_at": design["created_at"], "updated_at": design["updated_at"],
        "background": _file_brief(design.get("background_file_id")),
        "result": _file_brief(design.get("result_file_id")),
        "texts": design.get("texts_json") or [], "layers": design.get("layers_json") or [],
        "options": design.get("options_json") or {}, "placement": design.get("placement_json"),
        "fonts": F.kit_fonts(kit_id, snap), "fallback_font": F.FALLBACK_FAMILY,
        "logos": F.kit_logos(kit_id, snap), "colors": F.kit_colors(kit_id, snap),
        "kits": _kits(),
        "frame": {"id": frame["id"], "position": frame["position"], "count": count, "brief": frame["brief"],
                  "file_id": frame.get("file_id"), "clean_file_id": frame.get("clean_file_id"),
                  "status": frame["status"], "work_title": work.get("title")},
        "backgrounds": B.list_for(design["id"]),
    }


# ── changes ─────────────────────────────────────────────────────────────────

def _clean_options(value: Any, current: dict) -> dict:
    """What the panels last used (switches, the language, the default font): small, flat values."""
    if not isinstance(value, dict):
        raise AppError("bad_request", 400, "Options are an object")
    out = dict(current)
    for key, item in value.items():
        key = str(key)[:40]
        if item is None:
            out.pop(key, None)
        elif isinstance(item, bool | int | float):
            out[key] = item
        elif isinstance(item, str):
            out[key] = item[:200]
        elif key == "font" and isinstance(item, dict):
            out[key] = {"file_id": S.int_or_none(item.get("file_id")),
                        "family": C.clean_line(item.get("family"), 120)}
    if len(out) > MAX_OPTIONS:
        raise AppError("bad_request", 400, "Too many options")
    out["language"] = C.language(out.get("language"))
    return out


def patch(design_id: int, body: Any) -> dict:
    """Words, layers, options, the brand kit, the background. Nothing is paid."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    design = S.design_row(design_id)
    values: dict[str, Any] = {}
    texts = design.get("texts_json") or []
    layers = design.get("layers_json") or []
    if "texts" in body:
        texts = L.normalize_texts(body["texts"])
        values["texts_json"] = texts
    if "layers" in body:
        layers = L.normalize_layers(body["layers"])
    if "texts" in body or "layers" in body:
        values["layers_json"] = L.bind_texts(layers, texts)
    if "options" in body:
        values["options_json"] = _clean_options(body["options"], design.get("options_json") or {})
    if "kit_id" in body:
        kit_id = S.int_or_none(body["kit_id"])
        if kit_id and db.get("brand_kits", kit_id) is None:
            raise NotFound("brand_kit", id=kit_id)
        values["kit_id"] = kit_id
    if "background_file_id" in body:
        file_id = S.int_or_none(body["background_file_id"])
        if not file_id:
            raise AppError("bad_request", 400, "A background is required")
        width, height = _size_of(_image_row(file_id))
        values.update({"background_file_id": file_id, "width": width, "height": height})
    if values:
        values["status"] = "draft"
        S.update(design_id, values)
    return view(design_id)


def apply_layout(design_id: int, layout_id: Any) -> dict:
    """A ready layout replaces the layers, filled with the design's words."""
    from vf.modules.text import layouts as LT

    design = S.design_row(design_id)
    layout = LT.layout_row(layout_id)
    texts = design.get("texts_json") or []
    S.update(design_id, {"layers_json": L.from_layout(layout.get("layers_json") or [], texts), "status": "draft"})
    return view(design_id)


# ── «Place the text» ────────────────────────────────────────────────────────

def zones_for(frame: dict) -> Any:
    """The frame's own text map (where the text may go), if it has one."""
    return frame.get("text_zones_json") or None


def default_font(design: dict, snap: dict | None) -> dict | None:
    """The font new text layers get: the one picked in the panel, else the kit's first usable font."""
    chosen = (design.get("options_json") or {}).get("font")
    if isinstance(chosen, dict) and (chosen.get("file_id") or chosen.get("family")):
        return {"file_id": chosen.get("file_id"), "family": chosen.get("family") or ""}
    for font in F.kit_fonts(design.get("kit_id"), snap):
        if font["renderable"]:
            return {"file_id": font["file_id"], "family": font["family"]}
    return None


def _background(design: dict, max_side: int):
    if not design.get("background_file_id"):
        raise AppError("no_picture", 409, "The design has no background")
    try:
        data = files.read_bytes(design["background_file_id"])
    except (NotFound, OSError) as exc:
        raise AppError("no_picture", 409, "The background file is gone") from exc
    return data, R.open_background(data, max_side)


def _texts_to_place(design: dict) -> list[dict]:
    texts = [t for t in (design.get("texts_json") or []) if t.get("text")]
    if not texts:
        raise AppError("no_text", 400, "There are no words to place")
    return texts


async def place(design_id: int, body: Any) -> dict:
    """``{vision, replace, preview}``: free steps first; the paid vision call only when switched on.

    ``preview`` true answers what would go to the model ``{system, text, blocks}`` (``text`` empty =
    every block already has a place, nothing would be sent)."""
    body = body if isinstance(body, dict) else {}
    vision = C.flag(body, "vision")
    replace = C.flag(body, "replace")
    preview = C.flag(body, "preview")
    design = S.design_row(design_id)
    frame = S.frame_of(design)
    work = S.work_of(frame)
    snap = S.snapshot_for(design, work)
    texts = _texts_to_place(design)
    _, img = _background(design, PLACEMENT_SIDE)
    zones = zones_for(frame)
    first = frame["position"] == 0
    font = default_font(design, snap)
    current = design.get("layers_json") or []

    if preview:
        dry = await P.place(texts, current, img, zones=zones, vision=False, replace=replace, first=first, font=font)
        rest = [t for t in texts if dry["sources"].get(t["id"]) == "fallback"]
        if not rest:
            return {"system": "", "text": "", "blocks": 0}
        avoid = [P.layer_box(layer) for layer in dry["layers"]
                 if layer["type"] == "text" and layer.get("visible", True)
                 and dry["sources"].get(layer.get("block_id")) != "fallback"]
        return {**P.preview(rest, avoid, first=first), "blocks": len(rest)}

    result = await P.place(texts, current, img, zones=zones, vision=vision, replace=replace, first=first, font=font,
                           refs=S.refs_of(design))
    layers = L.bind_texts(L.normalize_layers(result["layers"]), design.get("texts_json") or [])
    placement = {"sources": result["sources"], "error": result["error"], "model_id": result["model_id"],
                 "cost_usd": round(result["cost_usd"] or 0, 6), "vision": vision, "at": db.now()}
    S.update(design_id, {"layers_json": layers, "placement_json": placement, "status": "draft"})
    S.add_cost(design_id, result["cost_usd"])
    return {"design": view(design_id), "placement": placement}


# ── drawing and saving ──────────────────────────────────────────────────────

def render_png(design_id: int, max_side: int = C.RENDER_MAX_SIDE) -> tuple[bytes, dict]:
    """The picture as «Save» would make it (nothing stored): ``(png, report)``.

    ``max_side`` smaller than the picture = a quick preview of the same layout."""
    design = S.design_row(design_id)
    work = S.work_of(S.frame_of(design))
    if not design.get("background_file_id"):
        raise AppError("no_picture", 409, "The design has no background")
    try:
        data = files.read_bytes(design["background_file_id"])
    except (NotFound, OSError) as exc:
        raise AppError("no_picture", 409, "The background file is gone") from exc
    side = min(max(int(max_side or C.RENDER_MAX_SIDE), 64), C.RENDER_MAX_SIDE)
    return R.render(data, design.get("layers_json") or [], logo_file_id=logo_of(design, S.snapshot_for(design, work)),
                    max_side=side)


def report_header(report: dict) -> str:
    return json.dumps(report, ensure_ascii=True, separators=(",", ":"))


def save(design_id: int) -> dict:
    """Draw, store the picture, put it into the frame as a new version and keep the layers."""
    design = S.design_row(design_id)
    frame = S.frame_of(design)
    background_id = design.get("background_file_id")
    png, report = render_png(design_id)
    stored = files.save_bytes(png, mime="image/png", name=f"frame-{frame['id']}-text.png",
                              source_type=C.SOURCE_DESIGN, source_id=design_id)
    try:
        studio.pick_picture(frame["id"], stored["id"], source="editor", source_ref={"design_id": design_id})
    except AppError:
        files.delete(stored["id"], force=True)
        raise
    layers = design.get("layers_json") or []
    texts = design.get("texts_json") or []
    # the studio's pick sets the clean picture to the new one; here the words are ours, so the
    # background without them is the clean picture (module 06 owns these two columns)
    db.update("frames", frame["id"], {"clean_file_id": background_id, "text_layers_json": layers,
                                      "updated_at": db.now()})
    blocks = [{"role": t["role"], "text": t["text"]} for t in texts if t.get("text")][:MAX_TEXT_BLOCKS]
    try:
        frame_view = studio.update_frame(frame["id"], {"text_blocks": blocks})
    except AppError as exc:  # the picture is saved; the frame's words stay as they were
        C.log.warning("text: frame %s words not synced (%s)", frame["id"], exc.code)
        frame_view = W.frame_public(W.frame_row(frame["id"]))
    now = db.now()
    db.insert("text_saves", {"design_id": design_id, "frame_id": frame["id"], "file_id": stored["id"],
                             "background_file_id": background_id, "texts_json": texts, "layers_json": layers,
                             "created_at": now})
    S.update(design_id, {"status": "saved", "result_file_id": stored["id"], "saved_at": now})
    C.publish(design_id, what="saved", frame_id=frame["id"], file_id=stored["id"])
    return {"design": view(design_id), "frame": frame_view, "report": report, "file": files.public(stored)}


__all__ = ["apply_layout", "default_font", "open_design", "patch", "place", "render_png", "save", "view",
           "zones_for"]
