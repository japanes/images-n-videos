"""The shoot brief: what the person filled in the «Ideas» window, cleaned and checked.

Every field is optional except the niche. An empty field stays empty in the text
the model reads (the master prompt has a rule not to invent facts for it). The
pictures go to the model in a fixed order — product ones first, then the visual
references — and the brief says how many of each are attached, so "the second
picture" means the same thing to both sides.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.core.google.gateway import Blob
from vf.modules.ideas import common as C

log = logging.getLogger("vf.ideas")

TEXT_FIELDS = ("brand", "want", "goal", "audience", "platform", "idea", "requirements")
FIELDS = ("niche", *TEXT_FIELDS, "count", "language", "product_refs", "product_note", "visual_refs", "visual_note")

PRODUCT_KIND = "product / model / brand references, first in the order"
VISUAL_KIND = "visual references, after the product ones"


def _count(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise AppError("ideas_bad_count", 400, "The number of frames is from 1 to 10", max=C.MAX_COUNT) from None
    if not 0 <= count <= C.MAX_COUNT:
        raise AppError("ideas_bad_count", 400, "The number of frames is from 1 to 10", max=C.MAX_COUNT)
    return count


def _pictures(value: Any, limit: int) -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "A list of picture ids is expected")
    out: list[int] = []
    for raw in value:
        if isinstance(raw, dict):
            raw = raw.get("file_id") or raw.get("id")
        try:
            file_id = int(raw)
        except (TypeError, ValueError):
            raise AppError("bad_request", 400, "A picture id is a number", value=raw) from None
        if file_id not in out:
            out.append(file_id)
    if len(out) > limit:
        raise AppError("ideas_too_many_pictures", 400, "Too many pictures", max=limit, count=len(out))
    for file_id in out:
        row = db.get("files", file_id)
        if row is None:
            raise NotFound("file", id=file_id)
        if row["kind"] != "image":
            raise AppError("ideas_not_a_picture", 400, "Only pictures can go into the brief", file_id=file_id)
    return out


def clean(data: Any) -> dict:
    """The brief as it is stored and sent. Refuses an empty niche and bad numbers."""
    if not isinstance(data, dict):
        raise AppError("bad_request", 400, "The brief must be an object")
    niche = C.clean_line(data.get("niche"), C.MAX_NICHE)
    if not niche:
        raise AppError("ideas_niche_empty", 400, "Say what is advertised first")
    language = str(data.get("language") or C.DEFAULT_LANGUAGE)
    if language not in C.LANGUAGES:
        raise AppError("ideas_bad_language", 400, "Unknown language", language=language,
                       allowed=list(C.LANGUAGES))
    out: dict[str, Any] = {"niche": niche}
    for name in TEXT_FIELDS:
        out[name] = C.clean_block(data.get(name), C.MAX_FIELD)
    out["count"] = _count(data.get("count"))
    out["language"] = language
    out["product_refs"] = _pictures(data.get("product_refs"), C.MAX_PRODUCT_REFS)
    out["product_note"] = C.clean_block(data.get("product_note"), C.MAX_NOTE)
    out["visual_refs"] = _pictures(data.get("visual_refs"), C.MAX_VISUAL_REFS)
    out["visual_note"] = C.clean_block(data.get("visual_note"), C.MAX_NOTE)
    return out


def file_ids(brief: dict) -> list[int]:
    product = list(brief.get("product_refs") or [])
    return product + [f for f in brief.get("visual_refs") or [] if f not in product]


def picture_count(brief: dict) -> int:
    return len(brief.get("product_refs") or []) + len(brief.get("visual_refs") or [])


def blob(file_id: int, *, max_side: int = C.REF_SIDE) -> Blob:
    """A picture as the text model takes it: JPEG, at most ``max_side`` on the long side."""
    from PIL import Image

    data = files.read_bytes(file_id)
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
    return Blob(buf.getvalue(), "image/jpeg", file_id)


def _load(ids: list[int]) -> list[Blob]:
    out = []
    for file_id in ids:
        try:
            out.append(blob(file_id))
        except (AppError, OSError, ValueError) as exc:   # deleted or unreadable: the brief counts what went
            log.warning("ideas: picture %s skipped: %s", file_id, exc)
    return out


def pictures(brief: dict) -> tuple[list[Blob], int, int]:
    """``(blobs, product_count, visual_count)`` — only the pictures that could be read."""
    product = _load(list(brief.get("product_refs") or []))
    visual = _load(list(brief.get("visual_refs") or []))
    return [*product, *visual], len(product), len(visual)


def ref_slot(note: str, count: int, kind: str) -> str:
    parts = []
    if count:
        parts.append(f"{count} image(s) attached to this message ({kind})." if count > 1
                     else f"1 image attached to this message ({kind}).")
    if note:
        parts.append(note)
    return "\n".join(parts)


def user_input(brief: dict, *, product_count: int, visual_count: int, research_block: str = "",
               scene_block: str = "") -> str:
    """The USER INPUT block of the brief (the SHOT_IDEAS_INPUT layer)."""
    from vf.modules import library

    count = int(brief.get("count") or 0)
    values = {
        "niche": brief.get("niche") or "", "brand": brief.get("brand") or "", "want": brief.get("want") or "",
        "count": str(count) if count else "", "goal": brief.get("goal") or "",
        "audience": brief.get("audience") or "", "platform": brief.get("platform") or "",
        "idea": brief.get("idea") or "",
        "product_refs": ref_slot(brief.get("product_note") or "", product_count, PRODUCT_KIND),
        "visual_refs": ref_slot(brief.get("visual_note") or "", visual_count, VISUAL_KIND),
        "requirements": brief.get("requirements") or "", "research": research_block, "scene": scene_block,
        "language": C.LANGUAGES.get(brief.get("language") or "", C.LANGUAGES[C.DEFAULT_LANGUAGE]),
    }
    return library.render_layer("SHOT_IDEAS_INPUT", values).strip()


__all__ = ["FIELDS", "blob", "clean", "file_ids", "picture_count", "pictures", "ref_slot", "user_input"]
