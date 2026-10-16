"""Drawing the cards of a set with the image studio (module 04).

The pictures are ordinary studio frames, so the chat shows them as an ordinary
picture result (its own message under the card) and everything the chat can do
with a picture — answer it, repeat it, accept a pilot — works on them.

* «Draw» on one card: a new work of one frame, its brief is the card's prompt.
* «Draw all»: one work with a frame per card, as a series. The first frame is the
  pilot; the others wait for «Accept» in the picture message and then follow its
  look. Only the pilot is paid at the press.

The work takes the chat's picture settings (model, shape, size, brand kit, style,
blocks) as they are now. The product pictures of the brief go to every frame only
when the person left «Product pictures into the frames» on in the window.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from vf.core import db
from vf.core.errors import AppError
from vf.modules.ideas import sets as S

log = logging.getLogger("vf.ideas")

# The studio settings of the chat a drawn card takes (the series switch is the press itself).
STUDIO_KEYS = ("subjects", "photo_style", "style", "style_sample", "kit_references", "text_mode", "blocks")


def _chat(chat_id: int) -> tuple[dict, dict]:
    """``(chat row, its picture settings)``."""
    from vf.modules.chat import store

    row = store.chat_row(chat_id)
    return row, store.image_settings(row)


def work_settings(image: dict, *, references: list[int]) -> dict:
    out = {k: copy.deepcopy(image.get(k)) for k in STUDIO_KEYS if k in image}
    out["references"] = list(references)
    out["ideas_brief"] = ""
    return out


def references_of(row_or_view: dict) -> list[int]:
    """The brief's product pictures, when the person let them into the frames."""
    options = row_or_view.get("options_json") or row_or_view.get("options") or {}
    if not options.get("product_to_frames"):
        return []
    brief = row_or_view.get("brief_json") or row_or_view.get("brief") or {}
    return list(brief.get("product_refs") or [])


def frame_price(chat_id: int, *, prompt: str, references: list[int]) -> dict:
    """The price of one frame drawn from ``prompt`` with this chat's settings.

    ``{usd, model_id, image_size, refusal}``; a setting the studio refuses (a model
    switched off, …) gives ``usd`` 0 and its error code in ``refusal``. Before the
    ideas are written the prompt is not known yet; the price does not depend on its
    words, so a stand-in is counted then."""
    from vf.modules import brand, studio
    from vf.modules.studio import compose
    from vf.modules.studio import works as W

    chat, image = _chat(chat_id)
    kit_id = chat.get("kit_id")
    try:
        settings = W.clean_settings(work_settings(image, references=references), copy.deepcopy(W.DEFAULT_SETTINGS))
        work = {"id": 0, "title": "", "settings_json": settings,
                "brand_json": brand.snapshot_kit(kit_id) if kit_id else None, "kit_id": kit_id,
                "model_id": image.get("model_id"), "image_size": image.get("image_size") or "1K",
                "aspect": image.get("aspect") or "1:1"}
        frame = {"id": 0, "work_id": 0, "position": 0, "brief": prompt.strip() or "-", "overrides_json": {},
                 "text_blocks_json": [], "versions_json": [], "file_id": None, "status": "empty",
                 "source": "generated"}
        plan = compose.plan_full(work, frame)
        price = studio.estimate({"action": "new", "model_id": image.get("model_id"),
                                 "image_size": image.get("image_size"), "count": 1,
                                 "input_images": plan.picture_count})
    except AppError as exc:
        return {"usd": 0.0, "model_id": image.get("model_id"), "image_size": image.get("image_size"),
                "refusal": exc.code}
    return {"usd": price["usd"], "model_id": price["model_id"], "image_size": price["image_size"],
            "refusal": None}


def _numbers(row: dict, numbers: Any) -> list[int]:
    """The cards to draw: ``"all"`` / None = every card with a prompt, or a list of numbers."""
    cards = [i for i in row.get("images_json") or [] if (i.get("prompt") or "").strip()]
    if numbers in (None, "all"):
        return [int(i["n"]) for i in cards]
    if not isinstance(numbers, list):
        raise AppError("bad_request", 400, "A list of card numbers is expected")
    out: list[int] = []
    for raw in numbers:
        item = S.image(row, raw)
        if not (item.get("prompt") or "").strip():
            raise AppError("ideas_prompt_empty", 400, "The card has no prompt", n=raw)
        if int(item["n"]) not in out:
            out.append(int(item["n"]))
    return out


def estimate(set_id: int, numbers: Any = None) -> dict:
    """Price of «Draw» (one number) or «Draw all» (every card).

    ``usd`` is what the press costs now (one picture: the single frame or the
    pilot), ``usd_all`` the whole series once the pilot is accepted."""
    row = S.set_row(set_id)
    picked = _numbers(row, numbers)
    if not picked:
        raise AppError("ideas_nothing_to_draw", 409, "The set has no cards to draw")
    first = S.image(row, picked[0])
    price = frame_price(row["chat_id"], prompt=first["prompt"], references=references_of(row))
    return {**price, "count": len(picked), "series": len(picked) > 1,
            "usd_all": round(price["usd"] * len(picked), 4)}


def _title(row: dict, items: list[dict]) -> str:
    name = ((row.get("concept_json") or {}).get("name") or (row.get("brief_json") or {}).get("niche") or "").strip()
    if len(items) == 1 and items[0].get("title"):
        return f"{name} — {items[0]['title']}" if name else items[0]["title"]
    return name


def _frame_items(work_id: int, started: dict) -> list[dict]:
    """The picture message's items, as the chat makes them for its own requests."""
    from vf.modules.studio import works as W

    queued = set(started.get("queued") or [])
    reasons = {s["frame_id"]: s.get("reason") for s in started.get("skipped") or []}
    items = []
    for f in W.frames_of(work_id):
        base = {"frame_id": f["id"], "work_id": work_id, "mode": "full"}
        if f["id"] in queued:
            items.append({**base, "job_id": f["job_id"], "status": "queued"})
        elif reasons.get(f["id"]) == "pilot_not_ready":
            items.append({**base, "job_id": None, "after_job": 0, "status": "waiting"})
        else:
            items.append({**base, "job_id": None, "status": "error",
                          "error_code": reasons.get(f["id"]) or "not_started", "error": None})
    return items


def _status(items: list[dict]) -> str:
    states = [i["status"] for i in items if i["status"] != "waiting"]
    if any(s in ("queued", "running") for s in states):
        return "running"
    if states and all(s == "error" for s in states):
        return "error"
    return "done"


def _drop_work(work_id: int) -> None:
    from vf.modules import studio

    try:
        studio.delete_work(work_id)
    except AppError:
        pass


def draw(set_id: int, numbers: Any = None) -> dict:
    """Start the studio for the cards; returns ``{set, message}`` (the picture message)."""
    from vf.modules import chat, studio
    from vf.modules.studio import works as W

    row = S.set_row(set_id)
    if row["status"] != "done":
        raise AppError("ideas_not_ready", 409, "The ideas are not written yet")
    picked = _numbers(row, numbers)
    if not picked:
        raise AppError("ideas_nothing_to_draw", 409, "The set has no cards to draw")
    cards = [S.image(row, n) for n in picked]
    chat_row, image = _chat(row["chat_id"])
    series = len(cards) > 1
    settings = work_settings(image, references=references_of(row))
    settings["series"] = series
    data = {"title": _title(row, cards), "settings": settings, "aspect": image.get("aspect") or "1:1",
            "image_size": image.get("image_size") or "1K", "frame_count": len(cards),
            "kit_id": chat_row.get("kit_id")}
    if image.get("model_id"):
        data["model_id"] = image["model_id"]
    work = studio.create_work(data)
    work_id = work["id"]
    try:
        frames = W.frames_of(work_id)
        for frame, card in zip(frames, cards, strict=True):
            studio.update_frame(frame["id"], {"brief": card["prompt"]})
        started = studio.start_all(work_id)
    except AppError:
        _drop_work(work_id)
        raise
    items = _frame_items(work_id, started)
    links = [("work", work_id), *[("frame", i["frame_id"]) for i in items]]
    message = chat.post_message(
        row["chat_id"], kind="image", type="result", mode="image", text=_title(row, cards),
        refs={"work_id": work_id}, links=links, status=_status(items),
        data={"items": items, "series": series, "action": "ideas", "ideas_id": set_id,
              "ideas_numbers": picked})
    now = db.now()
    by_number = {int(c["n"]): f["id"] for c, f in zip(cards, frames, strict=True)}
    images = []
    for item in S.set_row(set_id).get("images_json") or []:
        n = int(item.get("n") or 0)
        if n in by_number:
            item = {**item, "work_id": work_id, "frame_id": by_number[n], "message_id": message["id"],
                    "drawn_at": now}
        images.append(item)
    options = dict(row.get("options_json") or {})
    options.pop("draw_error_code", None)
    options.pop("draw_error", None)
    S.update(set_id, {"images_json": images, "options_json": options})
    return {"set": S.sync(set_id), "message": message}


def draw_safely(set_id: int) -> None:
    """The «one press» drawing after the ideas are written: a refusal is kept on the set, not raised."""
    try:
        draw(set_id, "all")
    except AppError as exc:
        log.warning("ideas set %s: drawing did not start: %s", set_id, exc.code)
        row = S.set_row(set_id)
        options = dict(row.get("options_json") or {})
        options.update(draw_error_code=exc.code, draw_error=getattr(exc, "raw", None) or exc.message)
        S.update(set_id, {"options_json": options})
        S.sync(set_id)


__all__ = ["STUDIO_KEYS", "draw", "draw_safely", "estimate", "frame_price", "references_of", "work_settings"]
