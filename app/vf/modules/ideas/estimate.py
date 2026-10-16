"""Prices before the buttons of the «Ideas» window and of the card's dice.

The window shows the parts separately, next to their switches: the niche research
(0 when it is already in the cache), the ideas themselves and the first picture.
A part is priced even while its switch is off, so the price is seen before it is
switched on; ``total_usd`` counts only the parts that are on. The models are the
ones of the roles now.
"""

from __future__ import annotations

from typing import Any

from vf.core import models_registry, pricing
from vf.core.errors import AppError
from vf.modules.ideas import common as C
from vf.modules.ideas import draw as D
from vf.modules.ideas import research as R
from vf.modules.ideas import sets as S


def _ids(value: Any) -> list[int]:
    out = []
    for raw in value if isinstance(value, list) else []:
        if isinstance(raw, dict):
            raw = raw.get("file_id") or raw.get("id")
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _model(role: str) -> tuple[dict | None, str | None]:
    try:
        return models_registry.model_for_role(role), None
    except AppError as exc:
        return None, exc.code


def write(body: Any) -> dict:
    """``{ideas_usd, research_usd, frame_usd, total_usd, …}`` for the window as it is filled now.

    ``research_usd`` / ``frame_usd`` are what the part costs when it is on (the frame
    needs ``chat_id``: it is drawn with the chat's picture settings). Lenient: an
    empty niche or a wrong field does not fail the price, the start checks them."""
    body = body if isinstance(body, dict) else {}
    brief = body.get("brief") if isinstance(body.get("brief"), dict) else {}
    product, visual = _ids(brief.get("product_refs")), _ids(brief.get("visual_refs"))
    pictures = len(product) + len(visual)
    research_on = bool(body.get("research"))
    draw_first = bool(body.get("draw_first"))

    ideas_model, ideas_refusal = _model(C.ROLE_IDEAS)
    ideas_usd = pricing.estimate_text(ideas_model, purpose=C.PURPOSE_IDEAS, input_images=pictures) \
        if ideas_model else 0.0

    research_usd = 0.0
    research_model, research_refusal = _model(C.ROLE_RESEARCH)
    cached = R.cached(brief.get("niche"), brief.get("platform"))
    if research_model and cached is None:
        research_usd = pricing.estimate_text(research_model, purpose=C.PURPOSE_RESEARCH, search=True)

    out = {
        "ideas_usd": ideas_usd, "ideas_model_id": ideas_model["id"] if ideas_model else None,
        "ideas_refusal": ideas_refusal,
        "research": research_on, "research_usd": research_usd,
        "research_model_id": research_model["id"] if research_model else None,
        "research_refusal": research_refusal, "research_cached": cached is not None,
        "research_cached_at": cached["created_at"] if cached else None,
        "draw_first": draw_first, "frame_usd": 0.0, "frame_model_id": None, "frame_refusal": None,
    }
    chat_id = body.get("chat_id")
    if draw_first or chat_id not in (None, ""):
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            raise AppError("bad_request", 400, "chat_id is needed for the price of the first frame") from None
        refs = product if body.get("product_to_frames") else []
        frame = D.frame_price(chat_id, prompt="", references=refs)
        out.update(frame_usd=frame["usd"], frame_model_id=frame["model_id"], frame_refusal=frame["refusal"])
    total = out["ideas_usd"] + (out["research_usd"] if research_on else 0.0) + (out["frame_usd"] if draw_first else 0.0)
    out["total_usd"] = round(total, 4)
    return out


def reroll(set_id: int) -> dict:
    """Price of the dice on one card: one text call with the brief's pictures, no search."""
    row = S.set_row(set_id)
    from vf.modules.ideas import brief as B

    model = models_registry.model_for_role(C.ROLE_IDEAS)
    usd = pricing.estimate_text(model, purpose=C.PURPOSE_FRAME, input_images=B.picture_count(row.get("brief_json") or {}))
    return {"usd": usd, "model_id": model["id"]}


__all__ = ["reroll", "write"]
