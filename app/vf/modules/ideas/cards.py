"""One card of a set: the person's own words, or the dice for a new idea of this frame only.

A card that is already a studio frame which has not been drawn yet (a waiting
frame of a series) gets the new prompt too, so «Accept» draws what the card says.
A drawn frame keeps its picture: the card is drawn again with «Draw».
"""

from __future__ import annotations

import logging
from typing import Any

from vf.core import db, prompts
from vf.core.errors import AppError
from vf.modules.ideas import brief as B
from vf.modules.ideas import common as C
from vf.modules.ideas import scene as SC
from vf.modules.ideas import sets as S
from vf.modules.ideas import write as WR

log = logging.getLogger("vf.ideas")

_busy: set[int] = set()   # sets whose card is being rewritten by the model right now


def _follow_frame(item: dict) -> None:
    """Pass the new prompt to the card's studio frame while that frame has no picture and is not drawing."""
    if not item.get("frame_id"):
        return
    from vf.modules import studio
    from vf.modules.studio.common import BUSY

    frame = db.get("frames", int(item["frame_id"]))
    if frame is None or frame.get("file_id") or frame["status"] in BUSY:
        return
    try:
        studio.update_frame(frame["id"], {"brief": item["prompt"]})
    except AppError as exc:
        log.warning("ideas: frame %s kept its brief: %s", frame["id"], exc.code)


def edit(set_id: int, n: Any, body: Any) -> dict:
    """The person's words for a card: ``{prompt, title?}``. Free."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    row = S.set_row(set_id)
    if row["status"] != "done":
        raise AppError("ideas_not_ready", 409, "The ideas are not written yet")
    item = dict(S.image(row, n))
    if "prompt" in body:
        prompt = C.clean_block(body.get("prompt"), C.MAX_PROMPT)
        if not prompt:
            raise AppError("ideas_prompt_empty", 400, "The card has no prompt", n=n)
        item["prompt"] = prompt
    if "title" in body:
        item["title"] = C.clean_line(body.get("title"), C.MAX_TITLE)
    item["edited"] = True
    S.put_image(set_id, item)
    _follow_frame(item)
    return S.sync(set_id)


def _others(row: dict, number: int) -> str:
    lines = []
    for item in row.get("images_json") or []:
        if int(item.get("n") or 0) != number:
            lines.append(f"{item['n']}. {item.get('title') or ''}: {item.get('prompt') or ''}".strip())
    return "\n".join(lines) or "(none)"


async def reroll(set_id: int, n: Any) -> dict:
    """The dice on one card: a new idea for this frame inside the same concept (one paid text call)."""
    row = S.set_row(set_id)
    if row["status"] != "done":
        raise AppError("ideas_not_ready", 409, "The ideas are not written yet")
    item = dict(S.image(row, n))
    if set_id in _busy:
        raise AppError("ideas_busy", 409, "A new idea for this set is being written")
    _busy.add(set_id)
    try:
        brief = row.get("brief_json") or {}
        found = row.get("research_json") or {}
        research_block = ""
        if row.get("research"):
            from vf.modules.ideas import research as R

            research_block = R.block(found.get("niche") or brief.get("niche") or "", found.get("summary") or "")
        images, product_count, visual_count = B.pictures(brief)
        text = B.user_input(brief, product_count=product_count, visual_count=visual_count,
                            research_block=research_block, scene_block=SC.as_block(row.get("scene_json") or {}))
        concept = row.get("concept_json") or {}
        current = f"{item['n']}. {item.get('title') or ''}: {item.get('prompt') or ''}"
        result = await prompts.run_prompt(
            C.PROMPT_FRAME, {"number": str(item["n"]), "concept_name": concept.get("name") or "",
                             "direction": concept.get("direction") or "", "others": _others(row, int(item["n"])),
                             "current": current, "user_input": text},
            purpose=C.PURPOSE_FRAME, images=images, refs=WR.refs_of(row))
        data = WR.answer_json(result)
        prompt = C.clean_block(data.get("prompt"), C.MAX_PROMPT)
        if not prompt:
            raise AppError("ideas_empty", 502, "The model returned no prompt")
        item.update(prompt=prompt, title=C.clean_line(data.get("title"), C.MAX_TITLE) or item.get("title") or "",
                    edited=False)
        S.put_image(set_id, item)
        _follow_frame(item)
        S.refresh_cost(set_id)
        return S.sync(set_id)
    except AppError:
        S.refresh_cost(set_id)   # a refused call is paid nothing, a failed one may be
        S.sync(set_id)
        raise
    finally:
        _busy.discard(set_id)


__all__ = ["edit", "reroll"]
