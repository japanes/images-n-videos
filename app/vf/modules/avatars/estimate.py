"""The price (and the time) before the button.

Every picture is priced with the model, size and number of pictures that would
really be sent with it. Pictures that cannot be drawn yet show their error code
at 0. The time is worked out from the person's own limits — how many requests run
at once and how many a minute Google is asked for — and from how long their own
recent pictures took, instead of the fixed «8 pictures a minute» of factory.
"""

from __future__ import annotations

import math
from typing import Any

from vf.core import db, models_registry, pricing, settings
from vf.core.errors import AppError
from vf.modules.avatars import compose, identity, store
from vf.modules.avatars.common import (
    BUSY,
    FACE_CODE,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    PURPOSE_FIX,
    PURPOSE_MASTER,
    PURPOSE_SHOT,
)

ACTIONS = ("describe", "candidates", "pack", "finish", "redraw", "fix")
DEFAULT_SECONDS = 20.0     # one picture, until the person's own history says otherwise
HISTORY = 20


# ── time ────────────────────────────────────────────────────────────────────

def seconds_per_picture(model_id: str | None) -> tuple[float, bool]:
    """Average time of the last successful pictures (this model first, then any). ``(seconds, from_history)``."""
    for where, params in ((" AND model_id = ?", [model_id]), ("", [])):
        if where and not model_id:
            continue
        rows = db.fetch_all("SELECT duration_ms FROM ai_calls WHERE kind = 'image' AND status = 'success' "
                            "AND stub = 0 AND duration_ms IS NOT NULL" + where + " ORDER BY id DESC LIMIT ?",
                            [*params, HISTORY])
        if len(rows) >= 3:
            return sum(r["duration_ms"] for r in rows) / len(rows) / 1000.0, True
    return DEFAULT_SECONDS, False


def time_for(count: int, model_id: str | None) -> dict:
    """``{seconds, per_picture, at_once, per_minute, from_history}`` for ``count`` pictures."""
    per, known = seconds_per_picture(model_id)
    at_once = max(1, min(int(settings.get("jobs.limit.avatar") or 1), int(settings.get("google.max_concurrency") or 1)))
    rpm = max(1, int(settings.get("google.max_rpm") or 1))
    seconds = math.ceil(count / at_once) * per if count else 0.0
    seconds = max(seconds, count / rpm * 60.0 if count > rpm else 0.0)
    return {"seconds": int(round(seconds)), "per_picture": round(per, 1), "at_once": at_once, "per_minute": rpm,
            "from_history": known}


# ── money ───────────────────────────────────────────────────────────────────

def _item(row: dict | None, usd: float, **extra: Any) -> dict:
    return {"photo_id": row["id"] if row else None, "shot_code": (row or {}).get("shot_code"),
            "usd": round(usd, 4), **extra}


def _total(items: list[dict], model_id: str | None) -> dict:
    priced = [i for i in items if not i.get("error")]
    return {"usd": round(sum(i["usd"] for i in priced), 4), "count": len(priced), "items": items,
            "model_id": model_id, "time": time_for(len(priced), model_id)}


def _plan_item(avatar: dict, row: dict, mode: str, fix: Any = None) -> dict:
    try:
        plan = compose.plan_for(avatar, row, mode, fix)
    except AppError as exc:
        return _item(row, 0, error=exc.code)
    purpose = PURPOSE_FIX if mode == "fix" else PURPOSE_SHOT
    usd = pricing.estimate_image(plan.model, count=1, image_size=plan.image_size,
                                 input_images=plan.picture_count, purpose=purpose)
    return _item(row, usd, model_id=plan.model["id"], image_size=plan.image_size,
                 input_images=plan.picture_count)


def _with_choice(avatar: dict, body: dict) -> dict:
    """The avatar as it will be with the model / number of candidates chosen in the dialog."""
    out = dict(avatar)
    if body.get("image_model_id"):
        out["image_model_id"] = models_registry.resolve("image", str(body["image_model_id"]))["id"]
    count = body.get("count", body.get("candidate_count"))
    if count is not None:
        try:
            out["candidate_count"] = min(max(int(count), MIN_CANDIDATES), MAX_CANDIDATES)
        except (TypeError, ValueError):
            pass
    return out


def _candidates(avatar: dict) -> dict:
    count = int(avatar.get("candidate_count") or 4)
    try:
        plan = compose.plan_candidate(avatar, 1)
    except AppError as exc:
        model = compose.image_model(avatar)
        return {**_total([_item(None, 0, error=exc.code)], model["id"]), "error": exc.code}
    one = pricing.estimate_image(plan.model, count=1, image_size=plan.image_size,
                                 input_images=plan.picture_count, purpose=PURPOSE_MASTER)
    items = [{"photo_id": None, "variation": i, "usd": round(one, 4), "model_id": plan.model["id"],
              "image_size": plan.image_size, "input_images": plan.picture_count} for i in range(1, count + 1)]
    return _total(items, plan.model["id"])


def _pack(avatar: dict, codes: Any) -> dict:
    slots = [s for s in store.slots_of(avatar["id"]) if s.get("shot_code") != FACE_CODE]
    if codes is None:
        rows = [s for s in slots if not s.get("file_id") and s["status"] not in BUSY]
    else:
        if not isinstance(codes, list):
            raise AppError("bad_request", 400, "codes must be a list of shot codes")
        wanted = {str(c) for c in codes}
        rows = [s for s in slots if s["shot_code"] in wanted]
    items = [_item(s, 0, error="avatar_photo_busy") if s["status"] in BUSY else _plan_item(avatar, s, "shot")
             for s in rows]
    return _total(items, compose.image_model(avatar)["id"])


def estimate(avatar_id: Any, body: Any) -> dict:
    """``{usd, count, items, model_id, time}`` for one action of the avatar chat."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    action = str(body.get("action") or "")
    if action not in ACTIONS:
        raise AppError("bad_request", 400, "Unknown action", action=action, allowed=list(ACTIONS))
    avatar = _with_choice(store.avatar_row(avatar_id), body)

    if action == "describe":
        if "mode" in body:
            avatar["init_mode"] = str(body["mode"])
        p = identity.price(avatar)
        return {"usd": p["usd"], "count": 1, "items": [], "model_id": p["model_id"], "photos": p["photos"],
                "time": None}
    if action == "candidates":
        return _candidates(avatar)
    if action in ("pack", "finish"):
        return _pack(avatar, None if action == "finish" else body.get("codes"))

    row = store.photo_row(body.get("photo_id"))
    if row["avatar_id"] != avatar["id"]:
        raise AppError("avatar_photo_foreign", 404, "The picture belongs to another avatar")
    if action == "redraw":
        return _total([_plan_item(avatar, row, "shot")], compose.image_model(avatar)["id"])
    return _total([_plan_item(avatar, row, "fix", body.get("text") or "fix")], compose.image_model(avatar)["id"])


__all__ = ["ACTIONS", "estimate", "seconds_per_picture", "time_for"]
