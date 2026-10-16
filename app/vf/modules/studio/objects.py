""""Find objects": one vision request that lists the things in the frame's picture
with their rectangles, so a correction can point at one of them.

The answer is kept on the frame together with the sha256 of the picture it was
found on: it is shown only while the frame shows that same picture. Asking again
for the same picture and the same focus costs nothing (the answer is reused, also
from another frame with the same picture).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from vf.core import db, files, google, prompts
from vf.core.errors import AppError
from vf.core.google import journal
from vf.core.google.boxes import box_2d_to_fractions
from vf.modules import library
from vf.modules.studio import imaging
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_FOCUS, MAX_OBJECTS, PURPOSE_OBJECTS, clean_text, file_sha, publish

PROMPT = "STUDIO_FIND_OBJECTS"
LIST_KEYS = ("objects", "regions", "items", "layers")
BOX_KEYS = ("box_2d", "box", "bbox")
MAX_LABEL = 80
MAX_ID = 32
MAX_ANSWER_TOKENS = 2000


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:MAX_ID].strip("-")


def normalize_objects(raw: Any) -> list[dict]:
    """The model's answer -> ``[{id, label, box: {x, y, w, h}}]`` (fractions 0..1).

    Accepts a bare list or a dict with the list under objects/regions/items/layers;
    a box under box_2d/box/bbox. Items without a usable box are dropped; ids are
    slugs of the label, unique within the answer."""
    items: Any = raw
    if isinstance(raw, dict):
        items = next((raw[k] for k in LIST_KEYS if isinstance(raw.get(k), list)), [])
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    used: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_box = next((item[k] for k in BOX_KEYS if item.get(k) is not None), None)
        box = box_2d_to_fractions(raw_box) if raw_box is not None else None
        if box is None:
            continue
        label = " ".join(str(item.get("label") or item.get("name") or "").split())[:MAX_LABEL]
        base = _slug(label) or f"r{len(out) + 1}"
        ident, n = base, 2
        while ident in used:
            suffix = f"-{n}"
            ident = base[:MAX_ID - len(suffix)] + suffix
            n += 1
        used.add(ident)
        out.append({"id": ident, "label": label, "box": box})
        if len(out) >= MAX_OBJECTS:
            break
    return out


def public(found: dict | None) -> dict | None:
    if not found:
        return None
    return {"items": found.get("items") or [], "focus": found.get("focus") or "", "at": found.get("at"),
            "cost_usd": found.get("cost_usd") or 0}


def cached(frame: dict, sha: str, focus: str) -> dict | None:
    """An earlier answer for this very picture and focus: this frame's first, then any frame's."""
    own = frame.get("objects_json")
    if own and own.get("sha") == sha and (own.get("focus") or "") == focus:
        return own
    for row in db.fetch_all("SELECT objects_json FROM frames WHERE objects_sha = ? AND id != ? ORDER BY id DESC",
                            (sha, frame["id"])):
        found = row.get("objects_json")
        if found and found.get("sha") == sha and (found.get("focus") or "") == focus:
            return found
    return None


def _with_objects(frame: dict, file_id: int, found: dict) -> list[dict]:
    """Copy the answer into the version that shows this picture (restoring it brings them back)."""
    versions = list(frame.get("versions_json") or [])
    for v in reversed(versions):
        if v.get("file_id") == file_id:
            v["objects"] = found
            break
    return versions


def _store(frame_id: int, file_id: int, sha: str, found: dict) -> None:
    with db.tx():
        current = db.get("frames", frame_id)
        if current is None:
            return
        values: dict[str, Any] = {"cost_usd": journal.cost_of(W.REF_FRAME, frame_id), "updated_at": db.now()}
        if current.get("file_id") == file_id:   # the picture did not change meanwhile
            values.update({"objects_json": found, "objects_sha": sha,
                           "versions_json": _with_objects(current, file_id, found)})
        db.update("frames", frame_id, values)
    publish("frame", work_id=current["work_id"], frame_id=frame_id, status=current["status"])


def is_cached(frame: dict, focus: Any = "") -> bool:
    """True when "find objects" would reuse an earlier answer (the price is then 0)."""
    if not frame.get("file_id"):
        return False
    row = db.get("files", frame["file_id"])
    if row is None or not row.get("sha256"):
        return False
    return cached(frame, row["sha256"], clean_text(focus, MAX_FOCUS)) is not None


async def find_objects(frame_id: int, focus: Any = "") -> dict:
    """List the things in the frame's current picture: ``{objects, cached, frame}``."""
    frame = W.frame_row(frame_id)
    file_id = frame.get("file_id")
    if not file_id:
        raise AppError("frame_no_picture", 409, "The frame has no picture yet")
    focus = clean_text(focus, MAX_FOCUS)
    sha = await asyncio.to_thread(file_sha, file_id)
    found = cached(frame, sha, focus)
    if found is not None:
        if frame.get("objects_json") is not found:
            _store(frame_id, file_id, sha, found)
        return {"objects": public(found), "cached": True, "frame": W.frame_public(W.frame_row(frame_id))}

    row = files.get(file_id)
    data = await asyncio.to_thread(files.read_bytes, file_id)
    small, mime = await asyncio.to_thread(imaging.to_width, data, row["mime"])
    rp = prompts.render(PROMPT)
    request = library.render_layer("IMAGE_SEGMENT_INPUT", {"max_objects": MAX_OBJECTS, "focus": focus}).strip()
    result = await google.generate(
        purpose=PURPOSE_OBJECTS, contents=[request, google.Blob(small, mime, file_id)],
        role=rp.role or "image_regions", system=rp.text, prompt=google.PromptInfo(rp.code, rp.version),
        response="json", schema=rp.schema, temperature=0, max_output_tokens=MAX_ANSWER_TOKENS,
        refs=[(W.REF_WORK, frame["work_id"]), (W.REF_FRAME, frame_id)],
    )
    found = {"sha": sha, "focus": focus, "items": normalize_objects(result.json), "model_id": result.model_id,
             "cost_usd": round(result.cost_usd, 6), "call_ids": result.call_ids, "at": db.now()}
    _store(frame_id, file_id, sha, found)
    return {"objects": public(found), "cached": False, "frame": W.frame_public(W.frame_row(frame_id))}
