"""Sending from the composer: what a message asks for, its price, and starting it.

A send becomes one action:

- ``new_image``: a new studio work with ``count`` frames (variants); the text is its brief;
- ``edit``: a reply to a picture — a studio correction of that frame;
- ``edit_base``: a picture attached with the role "base" — it goes into a new frame and is corrected;
- ``new_video``: a video run (module 11) with the text as its brief, one take;
- ``extend``: a reply to a video — one extension piece.

Every check runs before money is spent (``prepare``); the same function gives
the price shown on the button (``estimate``). The request message keeps a
snapshot of everything that went to the model, so it can be repeated as is.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from vf.core import db, files, models_registry, pricing, settings
from vf.core.errors import AppError, NotFound
from vf.modules import brand, studio
from vf.modules.chat import enhance, messages, store
from vf.modules.studio import compose
from vf.modules.studio import works as W
from vf.modules.studio.common import ASPECTS, BUSY, MAX_EDIT, PURPOSE_EDIT
from vf.modules.video import catalog as video_catalog
from vf.modules.video import extend as video_extend
from vf.modules.video import generate as video_generate
from vf.modules.video import runs as video_runs

MAX_TEXT = 4000
ACTIONS = ("new_image", "edit", "edit_base", "new_video", "extend")
ENHANCED_ACTIONS = ("new_image", "new_video")


@dataclass
class Prepared:
    action: str
    chat: dict
    mode: str
    text: str
    attachments: list[dict]
    image: dict
    video: dict
    kit_id: int | None
    enhance: bool
    reply: dict | None = None            # {message, index, item}
    mentions: list[dict] = field(default_factory=list)
    region: Any = None
    usd: float = 0.0                     # the generation
    enhance_usd: float = 0.0
    model_id: str | None = None
    count: int = 1
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # what the starter needs: picture ids, run, seconds…


# ── small checks ────────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _ids(attachments: list[dict], role: str) -> list[int]:
    return [a["file_id"] for a in attachments if a["role"] == role]


def _one(attachments: list[dict], role: str) -> int | None:
    found = _ids(attachments, role)
    return found[0] if found else None


def _attachments(mode: str, value: Any) -> list[dict]:
    """Pictures of the message with their roles; every one must be a stored picture."""
    limit = int(settings.get("general.max_attachments", 10) or 10)
    items = store.clean_attachments(value, limit=max(limit, 1))
    roles = store.IMAGE_ROLES if mode == "image" else store.VIDEO_ROLES
    for a in items:
        a["role"] = a["role"] or "reference"
        if a["role"] not in roles:
            raise AppError("chat_role_unknown", 400, "Unknown role of a picture", role=a["role"],
                           allowed=list(roles))
        try:
            row = files.get(a["file_id"])
        except NotFound:
            raise AppError("chat_attachment_missing", 400, "A picture was deleted",
                           file_id=a["file_id"]) from None
        if row["kind"] != "image":
            raise AppError("chat_attachment_not_image", 400, "Only pictures can be attached",
                           file_id=a["file_id"])
    for role in ("base", "first", "last"):
        if len(_ids(items, role)) > 1:
            raise AppError("chat_role_twice", 400, "This role can be given to one picture only", role=role)
    return items


def _reply(chat: dict, reply_to: Any, index: Any) -> dict | None:
    if not reply_to:
        return None
    try:
        row = db.get("chat_messages", int(reply_to))
    except (TypeError, ValueError):
        row = None
    if row is None or row["chat_id"] != chat["id"] or row["type"] != "result" or row["kind"] not in (
            "image", "video"):
        raise AppError("chat_reply_unknown", 404, "There is no such message to reply to", reply_to=reply_to)
    row = messages.hydrate(row)
    item = messages.result_item(row, index)
    if item.get("status") != "done" or not item.get("file_id"):
        raise AppError("chat_reply_not_ready", 409, "It is not ready yet")
    return {"message": row, "index": int(index or 0), "item": item}


def _check_text(text: str, limit: int, *, required: bool = True) -> None:
    if required and not text:
        raise AppError("chat_text_empty", 400, "Write what to make")
    if len(text) > limit:
        raise AppError("chat_text_too_long", 400, "The text is too long", max=limit, length=len(text))


def _nearest_aspect(file_id: int, fallback: str) -> str:
    row = files.get(file_id)
    if row.get("width") and row.get("height"):
        return video_catalog.nearest_aspect(row["width"] / row["height"], ASPECTS)
    return fallback


# ── preparing each action (all checks, the price) ───────────────────────────

def _studio_part(image: dict, text: str, mentions: list[dict] | tuple = (),
                 attachments: list[dict] | tuple = ()) -> dict:
    out = {k: copy.deepcopy(image.get(k)) for k in store.STUDIO_KEYS}
    subjects = list(image.get("subjects") or [])
    for m in mentions:
        if m["id"] not in subjects:
            subjects.append(m["id"])
    out["subjects"] = subjects
    out["references"] = _ids(list(attachments), "reference")
    out["ideas_brief"] = text
    return out


def _overrides(attachments: list[dict] | tuple) -> dict:
    attached = _ids(list(attachments), "subject")
    return W.clean_overrides({"attachments": attached}) if attached else {}


def synthetic(image: dict, kit_id: int | None, *, text: str = "", mentions: list[dict] | tuple = (),
              attachments: list[dict] | tuple = ()) -> tuple[dict, dict]:
    """A studio work and frame that are not saved: what a new picture request would be drawn with.

    Gives the price and the prompt blocks of the settings panel before anything exists."""
    kit = brand.snapshot_kit(kit_id) if kit_id else None
    work = {"id": 0, "title": "", "settings_json": W.clean_settings(_studio_part(image, text, mentions, attachments),
                                                                   copy.deepcopy(W.DEFAULT_SETTINGS)),
            "brand_json": kit, "kit_id": kit_id, "model_id": image.get("model_id"),
            "image_size": image.get("image_size") or "1K", "aspect": image.get("aspect") or "1:1"}
    frame = {"id": 0, "work_id": 0, "position": 0, "brief": "", "overrides_json": _overrides(attachments),
             "text_blocks_json": [], "versions_json": [], "file_id": None, "status": "empty", "source": "generated"}
    return work, frame


def _prepare_new_image(p: Prepared) -> None:
    s = p.image
    work, frame = synthetic(s, p.kit_id, text=p.text, mentions=p.mentions, attachments=p.attachments)
    plan = compose.plan_full(work, frame)
    count = int(s.get("count") or 1)
    series = bool(s.get("series")) and count > 1
    price = studio.estimate({"action": "new", "model_id": s.get("model_id"), "image_size": s.get("image_size"),
                             "count": 1 if series else count, "input_images": plan.picture_count})
    p.usd, p.model_id, p.count = price["usd"], price["model_id"], count
    p.extra.update(series=series, input_images=plan.picture_count, image_size=price["image_size"])


def _frame_of(item: dict) -> dict:
    try:
        return W.frame_row(int(item["frame_id"]))
    except (NotFound, KeyError, TypeError, ValueError):
        raise AppError("chat_reply_gone", 409, "This picture is no longer in the studio") from None


def _prepare_edit(p: Prepared) -> None:
    item = p.reply["item"]
    frame = _frame_of(item)
    if frame["status"] in BUSY:
        raise AppError("frame_busy", 409, "The frame is being drawn; wait or stop it")
    if not any(v.get("file_id") == item["file_id"] for v in frame.get("versions_json") or []):
        raise AppError("chat_reply_gone", 409, "This picture is no longer in the studio")
    work = W.work_row(frame["work_id"])
    shown = {**frame, "file_id": item["file_id"]}
    picked = compose.find_region(shown, p.region) if p.region else None
    plan = compose.plan_edit(work, shown, p.text, picked)
    eff = plan.eff
    p.usd = pricing.estimate_image(eff["model"], count=1, image_size=eff["image_size"],
                                   input_images=2 if picked else 1, purpose=PURPOSE_EDIT)
    p.model_id, p.count = eff["model_id"], 1
    p.extra.update(frame_id=frame["id"], work_id=frame["work_id"], image_size=eff["image_size"])


def _prepare_edit_base(p: Prepared) -> None:
    base = _one(p.attachments, "base")
    if len(p.attachments) > 1:
        raise AppError("chat_base_alone", 400, "A picture to change goes without other pictures")
    s = p.image
    model = models_registry.resolve("image", s.get("model_id") or None)
    size = W.pick_size(model, s.get("image_size") or "1K")
    aspect = _nearest_aspect(base, s.get("aspect") or "1:1")
    work = {"id": 0, "title": "", "brand_json": None, "kit_id": None, "model_id": model["id"], "image_size": size,
            "aspect": aspect, "settings_json": W.clean_settings({"text_mode": s.get("text_mode") or "none"},
                                                                copy.deepcopy(W.DEFAULT_SETTINGS))}
    frame = {"id": 0, "work_id": 0, "position": 0, "brief": "", "overrides_json": {}, "text_blocks_json": [],
             "versions_json": [], "file_id": base, "status": "done", "source": "library"}
    compose.plan_edit(work, frame, p.text, None)
    p.usd = pricing.estimate_image(model, count=1, image_size=size, input_images=1, purpose=PURPOSE_EDIT)
    p.model_id, p.count = model["id"], 1
    p.extra.update(base_file_id=base, aspect=aspect, image_size=size)


def _draft_run(chat: dict) -> dict | None:
    """The run made for «Write it for me» from this composer, if it is still unused."""
    run_id = store.draft(chat).get("video_run_id")
    if not run_id:
        return None
    try:
        run = video_runs.get_run(int(run_id))
    except NotFound:
        return None
    if video_runs.clips(run["id"], include_archived=True) or video_runs.active_job(run["id"]):
        return None
    return run


def _video_values(p: Prepared, text: str) -> dict:
    v = p.video
    values = {"brief": text, "first_frame_id": _one(p.attachments, "first"),
              "last_frame_id": _one(p.attachments, "last"), "references": _ids(p.attachments, "reference"),
              "camera_move": v.get("camera_move") or "", "sound": bool(v.get("sound", True))}
    for key in ("model_id", "duration", "resolution", "aspect"):
        if v.get(key) is not None:
            values[key] = v[key]
    return values


def _prepare_new_video(p: Prepared, *, use_draft: bool) -> None:
    run = _draft_run(p.chat) if use_draft else None
    values = _video_values(p, p.text)
    shown = dict(run or {"storyboard_json": {}})
    shown.update({k: v for k, v in values.items() if k != "references"})
    shown["references_json"] = values["references"]
    shown["sound"] = 1 if values["sound"] else 0
    if not shown.get("model_id"):
        shown["model_id"] = None
    preview = video_runs.take_preview(shown)
    if not preview["ready"]:
        raise AppError(preview["refusal"], 400, **(preview.get("refusal_details") or {}))
    p.usd, p.model_id, p.count = float(preview["estimate_usd"] or 0), preview["model_id"], 1
    p.warnings = list(preview.get("warnings") or [])
    p.extra.update(run_id=run["id"] if run else None, seconds=preview["seconds"],
                   resolution=preview["resolution"], aspect=preview["aspect"])


def _seconds(wanted: Any, lengths: list[int], fallback: Any) -> int:
    if wanted not in (None, ""):
        try:
            seconds = int(wanted)
        except (TypeError, ValueError):
            seconds = 0
        if seconds not in lengths:
            raise AppError("video_extend_length_unsupported", 400, seconds=seconds, allowed=lengths)
        return seconds
    if not lengths:
        raise AppError("video_extend_length_unsupported", 400, seconds=fallback, allowed=lengths)
    try:
        target = float(fallback)
    except (TypeError, ValueError):
        target = float(lengths[-1])
    return min(lengths, key=lambda n: (abs(n - target), -n))


def _prepare_extend(p: Prepared, wanted_seconds: Any) -> None:
    item = p.reply["item"]
    try:
        run = video_runs.get_run(int(item["run_id"]))
    except (NotFound, KeyError, TypeError, ValueError):
        raise AppError("chat_reply_gone", 409, "This video is no longer there") from None
    version = video_runs.version(run["id"], item.get("version")) if item.get("version") else None
    if version is None or version["archived"]:
        raise AppError("chat_reply_gone", 409, "This video is no longer there")
    info = video_extend.info(run["id"])
    if not info["available"] and info["reason"] != "video_extend_no_video":
        raise AppError(info["reason"] or "video_busy", 409)
    seconds = _seconds(wanted_seconds, list(info["lengths"] or []), p.video.get("duration"))
    if not p.text and not (run.get("brief") or "").strip():
        raise AppError("video_brief_empty", 400, "Describe the video first — the text is what gets filmed")
    price = video_extend.estimate(run["id"], [{"text": p.text, "seconds": seconds}])
    p.usd, p.model_id, p.count = float(price["total_usd"] or 0), price["model_id"], 1
    p.extra.update(run_id=run["id"], version=version["number"], seconds=seconds, resolution=price["resolution"],
                   length_after=price["length_after"])


def prepare(chat_id: int, body: Any, *, preset: dict | None = None) -> Prepared:
    """Every check of a send, and its price. Raises the refusal; nothing is saved.

    ``preset`` (repeat): the settings snapshot of an earlier request instead of the chat's."""
    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    chat = store.chat_row(chat_id)
    if chat.get("archived_at"):
        raise AppError("chat_archived", 409, "The chat is in the archive")
    mode = store._mode(body.get("mode") or chat["mode"])
    text = _text(body.get("text"))
    image = dict((preset or {}).get("image") or store.image_settings(chat))
    video = dict((preset or {}).get("video") or store.video_settings(chat))
    kit_id = (preset or {}).get("kit_id", chat.get("kit_id")) if preset is not None else chat.get("kit_id")
    reply = _reply(chat, body.get("reply_to"), body.get("reply_index"))
    attachments = _attachments(mode, body.get("attachments"))
    if reply:
        action = "edit" if reply["message"]["kind"] == "image" else "extend"
        mode = "image" if action == "edit" else "video"
        if attachments:
            raise AppError("chat_reply_no_pictures", 400, "A reply goes without attached pictures")
    elif mode == "image":
        action = "edit_base" if _one(attachments, "base") else "new_image"
    else:
        action = "new_video"
    p = Prepared(action=action, chat=chat, mode=mode, text=text, attachments=attachments, image=image,
                 video=video, kit_id=kit_id, reply=reply, region=body.get("region") or None,
                 enhance=bool(body.get("enhance")) and action in ENHANCED_ACTIONS)
    if action == "new_image":
        _check_text(text, MAX_TEXT)
        p.mentions = brand.match_mentions(text)
        _prepare_new_image(p)
    elif action == "edit":
        _check_text(text, MAX_EDIT)
        _prepare_edit(p)
    elif action == "edit_base":
        _check_text(text, MAX_EDIT)
        _prepare_edit_base(p)
    elif action == "new_video":
        _check_text(text, MAX_TEXT)
        _prepare_new_video(p, use_draft=preset is None)
    else:
        _check_text(text, video_extend.MAX_TEXT, required=False)
        _prepare_extend(p, body.get("extend_seconds"))
    if p.enhance:
        p.enhance_usd, _model = enhance.price(len(attachments))
    return p


def estimate(chat_id: int, body: Any, *, preset: dict | None = None) -> dict:
    """The price on the send button, or why it cannot be sent (the button explains it)."""
    try:
        p = prepare(chat_id, body, preset=preset)
    except AppError as exc:
        if isinstance(exc, NotFound) and exc.details.get("what") == "chat":
            raise
        return {"usd": None, "parts": {}, "action": None, "refusal": exc.code, "refusal_details": exc.details,
                "model_id": None, "count": 0, "warnings": []}
    return {"usd": round(p.usd + p.enhance_usd, 4),
            "parts": {"generation": round(p.usd, 4), "enhance": round(p.enhance_usd, 4)},
            "action": p.action, "refusal": None, "refusal_details": {}, "model_id": p.model_id, "count": p.count,
            "warnings": p.warnings, "extra": {k: v for k, v in p.extra.items() if k in (
                "series", "seconds", "resolution", "aspect", "image_size", "length_after", "input_images")}}


# ── the snapshot kept on the request ────────────────────────────────────────

def snapshot(p: Prepared) -> dict:
    image = {k: copy.deepcopy(v) for k, v in p.image.items()}
    out: dict[str, Any] = {
        "action": p.action, "mode": p.mode, "original_text": p.text, "sent_text": p.text,
        "enhance": p.enhance, "enhanced": False, "enhance_model_id": None, "enhance_cost_usd": 0.0,
        "enhance_prompt": None, "image": image, "video": copy.deepcopy(p.video), "kit_id": p.kit_id,
        "mentions": [{"id": m["id"], "name": m["name"]} for m in p.mentions], "reply": None, "extend": None,
        "region": p.region, "estimate_usd": round(p.usd + p.enhance_usd, 4), "model_id": p.model_id,
        "count": p.count, "warnings": p.warnings,
    }
    if p.reply:
        item = p.reply["item"]
        out["reply"] = {"message_id": p.reply["message"]["id"], "index": p.reply["index"],
                        "file_id": item.get("file_id"), "frame_id": item.get("frame_id"),
                        "run_id": item.get("run_id"), "version": item.get("version")}
    if p.action == "extend":
        out["extend"] = {"seconds": p.extra["seconds"], "model_id": p.model_id}
    if p.action == "new_video":
        out["video_sent"] = {"seconds": p.extra.get("seconds"), "resolution": p.extra.get("resolution"),
                             "aspect": p.extra.get("aspect")}
    if p.mode == "image":
        out["image_size"] = p.extra.get("image_size")
    return out


# ── starting ────────────────────────────────────────────────────────────────

def _frame_items(work_id: int, started: dict) -> list[dict]:
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


def _start_new_image(p: Prepared, text: str) -> dict:
    s = p.image
    data = {"title": store.auto_title(text), "settings": _studio_part(s, text, p.mentions, p.attachments),
            "aspect": s.get("aspect") or "1:1",
            "image_size": s.get("image_size") or "1K", "frame_count": p.count, "kit_id": p.kit_id}
    if s.get("model_id"):
        data["model_id"] = s["model_id"]
    work = studio.create_work(data)
    work_id = work["id"]
    try:
        overrides = _overrides(p.attachments)
        if overrides:
            for f in W.frames_of(work_id):
                studio.update_frame(f["id"], {"overrides": overrides})
        started = studio.start_all(work_id)
    except AppError:
        _drop_work(work_id)
        raise
    items = _frame_items(work_id, started)
    links = [("work", work_id), *[("frame", i["frame_id"]) for i in items]]
    return {"kind": "image", "items": items, "refs": {"work_id": work_id}, "links": links,
            "data": {"series": p.extra.get("series", False)}}


def _drop_work(work_id: int) -> None:
    try:
        studio.delete_work(work_id)
    except AppError:
        pass


def _version_index(frame: dict, file_id: int) -> int | None:
    found = None
    for i, v in enumerate(frame.get("versions_json") or []):
        if v.get("file_id") == file_id:
            found = i
    return found


def _start_edit(p: Prepared, text: str) -> dict:
    item = p.reply["item"]
    frame = _frame_of(item)
    if frame.get("file_id") != item["file_id"]:
        index = _version_index(frame, item["file_id"])
        if index is None:
            raise AppError("chat_reply_gone", 409, "This picture is no longer in the studio")
        studio.restore_version(frame["id"], index)
    started = studio.start_edit(frame["id"], text, p.region)
    one = {"frame_id": frame["id"], "work_id": frame["work_id"], "job_id": started["job_id"], "mode": "edit",
           "status": "queued", "base_file_id": item["file_id"]}
    return {"kind": "image", "items": [one], "refs": {"work_id": frame["work_id"]},
            "links": [("work", frame["work_id"]), ("frame", frame["id"])], "data": {}}


def _start_edit_base(p: Prepared, text: str) -> dict:
    s = p.image
    data = {"title": store.auto_title(text), "aspect": p.extra["aspect"], "image_size": p.extra["image_size"],
            "frame_count": 1, "settings": {"text_mode": s.get("text_mode") or "none"}, "model_id": p.model_id}
    work = studio.create_work(data)
    work_id = work["id"]
    frame_id = W.frames_of(work_id)[0]["id"]
    try:
        studio.pick_picture(frame_id, p.extra["base_file_id"], source="library")
        started = studio.start_edit(frame_id, text)
    except AppError:
        _drop_work(work_id)
        raise
    one = {"frame_id": frame_id, "work_id": work_id, "job_id": started["job_id"], "mode": "edit",
           "status": "queued", "base_file_id": p.extra["base_file_id"]}
    return {"kind": "image", "items": [one], "refs": {"work_id": work_id},
            "links": [("work", work_id), ("frame", frame_id)], "data": {}}


def _start_new_video(p: Prepared, text: str) -> dict:
    values = _video_values(p, text)
    values["title"] = store.auto_title(text)
    run_id = p.extra.get("run_id")
    created = False
    if run_id:
        video_runs.update_run(run_id, values)
    else:
        run_id = video_runs.create_run(values)["id"]
        created = True
    try:
        video_runs.start_take(run_id)
    except AppError:
        if created:
            try:
                video_runs.delete_run(run_id)
            except AppError:
                pass
        raise
    if p.extra.get("run_id"):
        store.set_draft_run(p.chat["id"], None)
    clip = video_runs.clips(run_id)[-1]
    one = {"run_id": run_id, "clip_id": clip["id"], "kind": "take", "status": "queued"}
    return {"kind": "video", "items": [one], "refs": {"run_id": run_id},
            "links": [("video_run", run_id), ("video_clip", clip["id"])], "data": {}}


def _start_extend(p: Prepared, text: str) -> dict:
    run_id = p.extra["run_id"]
    run = video_runs.get_run(run_id)
    if run.get("current_version") != p.extra["version"]:
        video_runs.choose_version(run_id, p.extra["version"])
    run = video_extend.start_extend(run_id, [{"text": text, "seconds": p.extra["seconds"]}], pause_each=True)
    clip_id = (run.get("extend_plan_json") or {})["steps"][0]["clip_id"]
    one = {"run_id": run_id, "clip_id": clip_id, "kind": "extend", "status": "queued",
           "source_version": p.extra["version"]}
    return {"kind": "video", "items": [one], "refs": {"run_id": run_id},
            "links": [("video_run", run_id), ("video_clip", clip_id)], "data": {}}


STARTERS = {"new_image": _start_new_image, "edit": _start_edit, "edit_base": _start_edit_base,
            "new_video": _start_new_video, "extend": _start_extend}


def _error_text(exc: AppError) -> str:
    return str(getattr(exc, "raw", "") or exc.message or exc.code)


def _publish(chat_id: int, message_id: int) -> None:
    store.publish(chat_id, what="message", message_id=message_id)


def _start(p: Prepared, text: str, request_id: int) -> int:
    chat_id = p.chat["id"]
    reply_to = p.reply["message"]["id"] if p.reply else None
    try:
        started = STARTERS[p.action](p, text)
    except AppError as exc:
        result_id = messages.add_message(
            chat_id, type="result", kind="image" if p.mode == "image" else "video", mode=p.mode,
            request_id=request_id, reply_to=reply_to, status="error", error_code=exc.code, error=_error_text(exc),
            data={"items": [], "action": p.action, "error_details": exc.details})
        _publish(chat_id, result_id)
        return result_id
    result_id = messages.add_message(
        chat_id, type="result", kind=started["kind"], mode=p.mode, request_id=request_id, reply_to=reply_to,
        refs=started["refs"], status="running",
        data={"items": started["items"], "action": p.action, **started["data"]})
    messages.link_refs(result_id, chat_id, started["links"])
    messages.hydrate(messages.message_row(result_id))
    _publish(chat_id, result_id)
    return result_id


def _after_request(p: Prepared, *, clear_draft: bool) -> None:
    chat = store.chat_row(p.chat["id"])
    values: dict[str, Any] = {"mode": p.mode, "updated_at": db.now()}
    if chat["title_auto"] and not chat["title"]:
        values["title"] = store.auto_title(p.text) or chat["title"]
    if clear_draft:
        old = store.draft(chat)
        values["draft_json"] = {**store.default_draft(), "enhance": old.get("enhance", False),
                                "video_run_id": old.get("video_run_id")}
    db.update("chats", chat["id"], values)
    store.publish(chat["id"], what="chat")


async def run(p: Prepared, *, clear_draft: bool) -> dict:
    """Save the request, improve the text when asked, start the generation, save the result."""
    chat_id = p.chat["id"]
    snap = snapshot(p)
    request_id = messages.add_message(
        chat_id, type="request", kind=p.mode, mode=p.mode, text=p.text, attachments=p.attachments,
        settings=snap, reply_to=p.reply["message"]["id"] if p.reply else None,
        status="enhancing" if p.enhance else "done")
    _after_request(p, clear_draft=clear_draft)
    _publish(chat_id, request_id)
    text = p.text
    if p.enhance:
        try:
            got = await enhance.improve(mode=p.mode, text=p.text, attachments=p.attachments,
                                        refs=[("chat", chat_id), (messages.SPEND_REF, request_id)])
        except AppError as exc:
            messages.update_message(request_id, {"status": "error", "error_code": exc.code,
                                                 "error": _error_text(exc)})
            _publish(chat_id, request_id)
            return {"request": messages.get_message(request_id), "result": None}
        text = got["text"]
        snap.update(sent_text=text, enhanced=True, enhance_model_id=got["model_id"],
                    enhance_cost_usd=got["cost_usd"],
                    enhance_prompt={"code": got["prompt_code"], "version": got["prompt_version"]})
        messages.update_message(request_id, {"status": "done", "cost_usd": got["cost_usd"], "settings_json": snap})
        _publish(chat_id, request_id)
    result_id = _start(p, text, request_id)
    return {"request": messages.get_message(request_id), "result": messages.get_message(result_id)}


async def send(chat_id: int, body: Any) -> dict:
    p = prepare(chat_id, body)
    return await run(p, clear_draft=True)


# ── repeating a request ─────────────────────────────────────────────────────

def _request_of(message_id: int) -> dict:
    row = messages.message_row(message_id)
    if row["type"] == "result" and row.get("request_id"):
        row = messages.message_row(row["request_id"])
    if row["type"] != "request":
        raise AppError("chat_not_request", 400, "Only a request can be repeated")
    return row


def _repeat_body(row: dict, original: bool) -> tuple[dict, dict]:
    snap = row.get("settings_json") or {}
    text = snap.get("original_text") if original else snap.get("sent_text")
    reply = snap.get("reply") or {}
    body = {"mode": row.get("mode") or snap.get("mode"), "text": text if text is not None else row.get("text"),
            "attachments": row.get("attachments_json") or [], "reply_to": reply.get("message_id"),
            "reply_index": reply.get("index"), "region": snap.get("region"), "enhance": False,
            "extend_seconds": (snap.get("extend") or {}).get("seconds")}
    preset = {"image": snap.get("image") or None, "video": snap.get("video") or None, "kit_id": snap.get("kit_id")}
    return body, preset


def repeat_estimate(message_id: int, original: bool = False) -> dict:
    row = _request_of(message_id)
    body, preset = _repeat_body(row, original)
    return estimate(row["chat_id"], body, preset=preset)


async def repeat(message_id: int, original: bool = False) -> dict:
    """«Repeat with the same settings» (``original``: «Send as I wrote»). A new paid request."""
    row = _request_of(message_id)
    body, preset = _repeat_body(row, original)
    p = prepare(row["chat_id"], body, preset=preset)
    return await run(p, clear_draft=False)


# ── actions on a result ─────────────────────────────────────────────────────

def _result(message_id: int, kind: str) -> dict:
    row = messages.message_row(message_id)
    if row["type"] != "result" or row["kind"] != kind:
        raise AppError("chat_item_unknown", 404, "This message has no such result")
    return row


def accept_pilot_estimate(message_id: int) -> dict:
    row = _result(message_id, "image")
    work_id = (row.get("refs_json") or {}).get("work_id")
    return studio.estimate({"action": "accept_pilot", "work_id": work_id})


def accept_pilot(message_id: int) -> dict:
    """Series: the first picture is approved, the others are drawn after it."""
    row = _result(message_id, "image")
    work_id = (row.get("refs_json") or {}).get("work_id")
    if not work_id:
        raise AppError("chat_item_unknown", 404, "This message has no studio work")
    started = studio.accept_pilot(int(work_id))
    queued = set(started.get("queued") or [])
    data = dict(row.get("data_json") or {})
    items = []
    for item in data.get("items") or []:
        if item.get("status") == "waiting" and item.get("frame_id") in queued:
            frame = W.frame_row(item["frame_id"])
            item = {**item, "job_id": frame["job_id"], "status": "queued"}
        items.append(item)
    data["items"] = items
    data["pilot_accepted"] = True
    messages.update_message(message_id, {"data_json": data, "status": "running" if queued else row["status"]})
    messages.hydrate(messages.message_row(message_id))
    _publish(row["chat_id"], message_id)
    return messages.get_message(message_id)


def cancel(message_id: int) -> dict:
    """Stop what this result is still making."""
    row = messages.hydrate(messages.message_row(message_id))
    if row["type"] != "result":
        raise AppError("chat_item_unknown", 404, "Only a result can be stopped")
    data = dict(row.get("data_json") or {})
    items = []
    stopped_runs: set[int] = set()
    for item in data.get("items") or []:
        if item.get("status") in messages.FINAL:
            items.append(item)
            continue
        if item.get("status") == "waiting":
            items.append({**item, "status": "cancelled", "error_code": "cancelled"})
            continue
        if row["kind"] == "image" and item.get("frame_id"):
            frame = db.get("frames", int(item["frame_id"]))
            if frame and frame.get("job_id") == item.get("job_id"):
                studio.cancel_frame(frame["id"])
        elif row["kind"] == "video" and item.get("run_id") and item["run_id"] not in stopped_runs:
            stopped_runs.add(item["run_id"])
            video_runs.stop_run(int(item["run_id"]))
        items.append(item)
    data["items"] = items
    messages.update_message(message_id, {"data_json": data})
    messages.hydrate(messages.message_row(message_id))
    _publish(row["chat_id"], message_id)
    return messages.get_message(message_id)


def _image_result(chat_id: int, items: list[dict], *, work_id: int, action: str, reply_to: int | None = None,
                  cost: float = 0.0) -> int:
    message_id = messages.add_message(chat_id, type="result", kind="image", mode="image", reply_to=reply_to,
                                      refs={"work_id": work_id}, data={"items": items, "action": action},
                                      status=messages.aggregate(items), cost_usd=cost)
    messages.link_refs(message_id, chat_id, [("work", work_id), *[("frame", i["frame_id"]) for i in items]])
    _publish(chat_id, message_id)
    return message_id


async def take_frame(message_id: int, body: Any) -> dict:
    """«Take frame»: a picture from the video goes into a new studio frame and into the chat (free)."""
    body = body if isinstance(body, dict) else {}
    row = _result(message_id, "video")
    item = messages.result_item(messages.hydrate(row), body.get("index"))
    if item.get("status") != "done" or not item.get("run_id"):
        raise AppError("chat_reply_not_ready", 409, "The video is not ready yet")
    at = body.get("at") or "last"
    if not isinstance(at, str):
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise AppError("video_frame_at", 400, at=at) from None
    picture = await video_generate.take_frame(int(item["run_id"]), at=at, version=item.get("version"))
    chat = store.chat_row(row["chat_id"])
    image = store.image_settings(chat)
    run = video_runs.get_run(int(item["run_id"]))
    data = {"title": video_runs.job_title(run), "aspect": _nearest_aspect(picture["id"], image["aspect"]),
            "frame_count": 1}
    work = studio.create_work(data)
    frame_id = W.frames_of(work["id"])[0]["id"]
    studio.pick_picture(frame_id, picture["id"], source="video_frame",
                        source_ref={"run_id": item["run_id"], "version": item.get("version"), "at": str(at)})
    one = {"frame_id": frame_id, "work_id": work["id"], "file_id": picture["id"], "status": "done",
           "mode": "video_frame", "cost_usd": 0.0, "job_id": None}
    new_id = _image_result(row["chat_id"], [one], work_id=work["id"], action="take_frame", reply_to=message_id)
    return messages.get_message(new_id)


def _chat_image_items(chat_id: int) -> list[dict]:
    rows = db.fetch_all("SELECT data_json FROM chat_messages WHERE chat_id = ? AND type = 'result' AND kind = 'image'",
                        (chat_id,))
    return [i for r in rows for i in (r.get("data_json") or {}).get("items") or []]


def from_viewer(chat_id: int, body: Any) -> dict:
    """After the full-screen viewer: a picture made or chosen there is added to the feed once."""
    body = body if isinstance(body, dict) else {}
    store.chat_row(chat_id)
    try:
        frame = W.frame_row(int(body.get("frame_id") or 0))
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "frame_id is expected") from None
    known = _chat_image_items(chat_id)
    jobs_seen = {i.get("job_id") for i in known if i.get("job_id")}
    files_seen = {i.get("file_id") for i in known if i.get("file_id")}
    base = {"frame_id": frame["id"], "work_id": frame["work_id"]}
    if frame["status"] in BUSY and frame.get("job_id"):
        if frame["job_id"] in jobs_seen:
            return {"message": None}
        job = db.get("jobs", frame["job_id"]) or {}
        mode = (job.get("payload_json") or {}).get("mode") or "full"
        one = {**base, "job_id": frame["job_id"], "mode": mode, "status": "queued"}
    elif frame.get("file_id") and frame["file_id"] not in files_seen:
        v = messages._version_of(frame, frame["file_id"])
        one = {**base, "job_id": None, "mode": "viewer", "status": "done", "file_id": frame["file_id"],
               "cost_usd": round(v.get("cost_usd") or 0, 6), "prompt_text": v.get("prompt_text"),
               "model_id": v.get("model_id"), "image_size": v.get("image_size")}
    else:
        return {"message": None}
    new_id = _image_result(chat_id, [one], work_id=frame["work_id"], action="viewer",
                           reply_to=body.get("reply_to") or None, cost=one.get("cost_usd") or 0.0)
    messages.hydrate(messages.message_row(new_id))
    return {"message": messages.get_message(new_id)}


# ── «Write it for me» in video mode ─────────────────────────────────────────

def video_draft(chat_id: int, body: Any) -> dict:
    """The run behind the composer's «Write it for me»: created or brought up to date with the
    composer (text, pictures, the chat's video settings). Nothing is paid here."""
    body = body if isinstance(body, dict) else {}
    chat = store.chat_row(chat_id)
    attachments = _attachments("video", body.get("attachments"))
    text = _text(body.get("text"))
    _check_text(text, MAX_TEXT, required=False)
    p = Prepared(action="new_video", chat=chat, mode="video", text=text, attachments=attachments, image={},
                 video=store.video_settings(chat), kit_id=None, enhance=False)
    values = _video_values(p, text)
    run = _draft_run(chat)
    if run is None:
        run_id = video_runs.create_run(values)["id"]
        store.set_draft_run(chat_id, run_id)
    else:
        run_id = run["id"]
        video_runs.update_run(run_id, values)
    from vf.modules import video

    return {"run_id": run_id, "run": video.public_run(run_id)}


def pictures(chat_id: int, limit: int = 60) -> dict:
    """Pictures of this chat for the paperclip: finished pictures of results and attached ones."""
    store.chat_row(chat_id)
    rows = db.fetch_all("SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY position DESC", (chat_id,))
    out: list[dict] = []
    seen: set[int] = set()

    def add(file_id: Any, message_id: int) -> None:
        if not file_id or file_id in seen or len(out) >= limit:
            return
        f = messages._file(file_id)
        if f and f["kind"] == "image":
            seen.add(file_id)
            out.append({**f, "message_id": message_id})

    for r in rows:
        if r["type"] == "result" and r["kind"] == "image":
            for i in (r.get("data_json") or {}).get("items") or []:
                if i.get("status") == "done":
                    add(i.get("file_id"), r["id"])
        for a in r.get("attachments_json") or []:
            add(a.get("file_id"), r["id"])
    return {"items": out}


__all__ = ["ACTIONS", "Prepared", "accept_pilot", "accept_pilot_estimate", "cancel", "estimate", "from_viewer",
           "pictures", "prepare", "repeat", "repeat_estimate", "run", "send", "snapshot", "synthetic",
           "take_frame", "video_draft"]
