"""The price before the button: what a studio action will cost, frame by frame.

Each frame is priced with the pictures that would really be sent with it (the
number of input pictures changes the price), with the model and size it would
really use. Frames that cannot be drawn yet show their error code at 0.
"""

from __future__ import annotations

from typing import Any

from vf.core import models_registry, pricing
from vf.core.errors import AppError
from vf.modules.studio import compose, generate, objects
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_FRAMES, PURPOSE_EDIT, PURPOSE_FRAME, PURPOSE_OBJECTS

ACTIONS = ("generate_all", "frame", "edit", "find_objects", "accept_pilot", "new")


def _item(frame: dict, usd: float, **extra: Any) -> dict:
    return {"frame_id": frame["id"], "position": frame["position"], "usd": round(usd, 4), **extra}


def _frame_item(work: dict, frame: dict) -> dict:
    try:
        plan = compose.plan_full(work, frame)
    except AppError as exc:
        return _item(frame, 0, error=exc.code)
    eff = plan.eff
    usd = pricing.estimate_image(eff["model"], count=1, image_size=eff["image_size"],
                                 input_images=plan.picture_count, purpose=PURPOSE_FRAME)
    return _item(frame, usd, model_id=eff["model_id"], image_size=eff["image_size"],
                 input_images=plan.picture_count)


def _accepted(work: dict) -> dict:
    """The work as it will be once the pilot is accepted (its picture goes to the other frames)."""
    s = dict(W.settings_of(work))
    pilot = W.pilot_frame(work)
    s["pilot_accepted"], s["pilot_frame_id"] = True, pilot["id"] if pilot else None
    return {**work, "settings_json": s}


def _total(items: list[dict]) -> dict:
    priced = [i for i in items if not i.get("error")]
    return {"usd": round(sum(i["usd"] for i in priced), 4), "count": len(priced), "items": items}


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def estimate(body: dict) -> dict:
    """``{usd, count, items: [{frame_id, position, usd, model_id, image_size, input_images, error?}]}``."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    action = str(body.get("action") or "")
    if action not in ACTIONS:
        raise AppError("bad_request", 400, "Unknown action", action=action, allowed=list(ACTIONS))

    if action == "new":   # a work that does not exist yet: model, size, frames, pictures sent
        model = models_registry.resolve("image", body.get("model_id") or None)
        size = W.pick_size(model, str(body.get("image_size") or "1K"))
        count = _int(body.get("count"), 1, 0, MAX_FRAMES)
        one = pricing.estimate_image(model, count=1, image_size=size,
                                     input_images=_int(body.get("input_images"), 0, 0, 14), purpose=PURPOSE_FRAME)
        return {"usd": round(one * count, 4), "count": count, "items": [],
                "model_id": model["id"], "image_size": size}

    if action in ("generate_all", "accept_pilot"):
        work = W.work_row(int(body.get("work_id") or 0))
        if action == "generate_all":
            targets, _skipped = generate.all_targets(work)
        else:
            work = _accepted(work)
            targets = generate.pilot_targets(work)
        return _total([_frame_item(work, f) for f in targets])

    frame = W.frame_row(int(body.get("frame_id") or 0))
    work = W.work_row(frame["work_id"])
    if action == "frame":
        return _total([_frame_item(work, frame)])

    if action == "edit":
        try:
            eff = W.effective(work, frame)
        except AppError as exc:
            return _total([_item(frame, 0, error=exc.code)])
        pictures = 2 if body.get("region") else 1
        usd = pricing.estimate_image(eff["model"], count=1, image_size=eff["image_size"], input_images=pictures,
                                     purpose=PURPOSE_EDIT)
        return _total([_item(frame, usd, model_id=eff["model_id"], image_size=eff["image_size"],
                             input_images=pictures)])

    # find_objects
    if objects.is_cached(frame, body.get("focus") or ""):
        return _total([_item(frame, 0, cached=True)])
    model = models_registry.model_for_role("image_regions")
    usd = pricing.estimate_text(model, purpose=PURPOSE_OBJECTS, input_images=1)
    return _total([_item(frame, usd, model_id=model["id"], cached=False)])
