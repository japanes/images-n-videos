"""The price before the button, for every paid button of the tool in one answer.

Text buttons are priced with the model of their role (``text_placement`` / ``image_text``),
the «Generate» tab with the frame's image model and size. A button whose model cannot be used
gets ``refusal`` (the registry's error code) and 0: the panel shows why instead of a price.
"""

from __future__ import annotations

from typing import Any

from vf.core import models_registry, pricing
from vf.core.errors import AppError
from vf.modules.studio import works as W
from vf.modules.text import common as C
from vf.modules.text import store as S


def _model(role: str) -> tuple[dict | None, str | None]:
    try:
        return models_registry.model_for_role(role), None
    except AppError as exc:
        return None, exc.code


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def _text(role: str, purpose: str, *, count: int = 1, images: int = 0) -> dict:
    model, refusal = _model(role)
    if model is None:
        return {"usd": 0, "count": count, "model_id": None, "refusal": refusal}
    usd = pricing.estimate_text(model, purpose=purpose, input_images=images, count=count)
    return {"usd": round(usd, 4), "count": count, "model_id": model["id"], "refusal": None}


def _background(design: dict | None, count: int, use_current: bool) -> dict:
    if design is None:
        return {"usd": 0, "count": count, "model_id": None, "refusal": "no_design"}
    try:
        frame = S.frame_of(design)
        eff = W.effective(S.work_of(frame), frame)
    except AppError as exc:
        return {"usd": 0, "count": count, "model_id": None, "refusal": exc.code}
    usd = pricing.estimate_image(eff["model"], count=count, image_size=eff.get("image_size"),
                                 input_images=1 if use_current else 0, purpose=C.PURPOSE_BACKGROUND)
    return {"usd": round(usd, 4), "count": count, "model_id": eff["model_id"],
            "image_size": eff.get("image_size"), "refusal": None}


def estimate(params: Any) -> dict:
    """``{design_id?, variants: 1..4, backgrounds: 1..4, use_current}`` →
    ``{placement, write, variants, humanize, background}``, each ``{usd, count, model_id, refusal}``."""
    params = params if isinstance(params, dict) else {}
    design_id = S.int_or_none(params.get("design_id"))
    design = S.design_row(design_id) if design_id else None
    n_variants = _int(params.get("variants"), 1, 1, C.MAX_VARIANTS)
    n_backgrounds = _int(params.get("backgrounds"), 1, 1, C.MAX_BACKGROUNDS)
    use_current = str(params.get("use_current") or "").lower() in ("1", "true", "yes")
    return {
        "placement": _text(C.ROLE_PLACEMENT, C.PURPOSE_PLACEMENT, images=1),
        "write": _text(C.ROLE_TEXT, C.PURPOSE_WRITE),
        "variants": _text(C.ROLE_TEXT, C.PURPOSE_VARIANTS, count=n_variants),
        "humanize": _text(C.ROLE_TEXT, C.PURPOSE_HUMANIZE),
        "background": _background(design, n_backgrounds, use_current),
    }


__all__ = ["estimate"]
