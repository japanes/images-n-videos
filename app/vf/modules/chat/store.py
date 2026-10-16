"""Chats: storage, settings of a chat, the draft of the composer, the list.

A chat keeps its own picture and video settings (they start from the general
settings and the default models) and the draft of the composer (autosaved).
"""

from __future__ import annotations

import copy
from typing import Any

from vf.core import db, events, models_registry, settings
from vf.core.errors import AppError, NotFound
from vf.modules import brand
from vf.modules.studio import works as studio_works
from vf.modules.studio.common import ASPECTS, MAX_FRAMES
from vf.modules.video import catalog as video_catalog

MODES = ("image", "video")
KINDS = ("normal", "avatar")
IMAGE_ROLES = ("reference", "subject", "base")
VIDEO_ROLES = ("first", "last", "reference")
MAX_TITLE = 120
TITLE_WORDS = 6
TITLE_CHARS = 60
MAX_DRAFT = 8000
MAX_DRAFT_ATTACHMENTS = 14
VIDEO_SECONDS = 8   # asked of the default video model for a new chat; snapped to what it allows

# The keys of image settings handled by the studio's own checks.
STUDIO_KEYS = ("subjects", "photo_style", "style", "style_sample", "kit_references", "text_mode", "blocks",
               "series")
IMAGE_KEYS = ("model_id", "aspect", "image_size", "count", *STUDIO_KEYS)
VIDEO_KEYS = ("model_id", "duration", "resolution", "aspect", "camera_move", "sound")

# Variants of one request are frames of one work. "Slide i of n" is a carousel rule,
# not a rule for variants: a new chat starts with that block off (a visible tumbler).
CHAT_BLOCKS = {"slide_position": False}


def publish(chat_id: int, **data: Any) -> None:
    events.publish("chat.updated", {"chat_id": chat_id, **data})


# ── defaults ────────────────────────────────────────────────────────────────

def _default_image_model() -> str | None:
    try:
        return models_registry.resolve("image", None)["id"]
    except AppError:
        return None


def default_image_settings() -> dict:
    return {
        "model_id": _default_image_model(), "aspect": "1:1", "image_size": "1K",
        "count": int(settings.get("general.variants", 3) or 3), "subjects": [], "style": None,
        "photo_style": None, "style_sample": False, "kit_references": True, "text_mode": "none",
        "blocks": dict(CHAT_BLOCKS), "series": False,
    }


def default_video_settings() -> dict:
    try:
        m = video_catalog.model(None)
    except AppError:
        return {"model_id": None, "duration": None, "resolution": None, "aspect": None, "camera_move": "",
                "sound": True}
    fit = video_catalog.fit_settings(m, seconds=VIDEO_SECONDS, resolution=None, aspect=None)
    return {"model_id": m["id"], "duration": fit["duration"], "resolution": fit["resolution"],
            "aspect": fit["aspect"], "camera_move": "", "sound": True}


def default_draft() -> dict:
    return {"text": "", "attachments": [], "reply_to": None, "reply_index": 0, "enhance": False,
            "video_run_id": None}


# ── checks of what the browser sends ────────────────────────────────────────

def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, f"{name} must be a number", field=name) from None
    if not low <= number <= high:
        raise AppError("bad_request", 400, f"{name} is from {low} to {high}", field=name, min=low, max=high)
    return number


def clean_image_settings(patch: Any, current: dict) -> dict:
    """Merge a partial change of the picture settings (keys left out stay)."""
    if not isinstance(patch, dict):
        raise AppError("bad_request", 400, "Settings must be an object")
    out = copy.deepcopy(current)
    if "model_id" in patch:
        out["model_id"] = models_registry.resolve("image", patch["model_id"])["id"] if patch["model_id"] else None
    if "aspect" in patch:
        aspect = str(patch["aspect"] or "")
        if aspect not in ASPECTS:
            raise AppError("bad_aspect", 400, "Unknown aspect ratio", aspect=aspect, allowed=list(ASPECTS))
        out["aspect"] = aspect
    if "image_size" in patch:
        size = str(patch["image_size"] or "")
        if size not in studio_works.IMAGE_SIZES:
            raise AppError("bad_size", 400, "Unknown picture size", size=size,
                           allowed=list(studio_works.IMAGE_SIZES))
        out["image_size"] = size
    if "count" in patch:
        out["count"] = _int(patch["count"], "count", 1, MAX_FRAMES)
    studio_part = {k: patch[k] for k in STUDIO_KEYS if k in patch}
    if studio_part:
        current_studio = {k: out.get(k) for k in STUDIO_KEYS}
        current_studio["blocks"] = dict(out.get("blocks") or {})
        if isinstance(studio_part.get("blocks"), dict):
            # the panel sends one switch at a time; the studio replaces the whole map
            studio_part["blocks"] = {**current_studio["blocks"], **studio_part["blocks"]}
        cleaned = studio_works.clean_settings(studio_part, current_studio)
        out.update({k: cleaned[k] for k in STUDIO_KEYS if k in cleaned})
    return {k: out.get(k) for k in IMAGE_KEYS}


def clean_video_settings(patch: Any, current: dict) -> dict:
    """Merge a partial change of the video settings; model changes snap the rest."""
    if not isinstance(patch, dict):
        raise AppError("bad_request", 400, "Settings must be an object")
    out = copy.deepcopy(current)
    if "camera_move" in patch:
        out["camera_move"] = video_catalog.check_camera_move(patch["camera_move"])
    if "sound" in patch:
        out["sound"] = bool(patch["sound"])
    shape = {"model_id", "duration", "resolution", "aspect"} & set(patch)
    if shape:
        m = video_catalog.model(patch.get("model_id", out.get("model_id")) or None)
        fit = video_catalog.fit_settings(m, seconds=patch.get("duration", out.get("duration")),
                                         resolution=patch.get("resolution", out.get("resolution")),
                                         aspect=patch.get("aspect", out.get("aspect")))
        out.update({"model_id": m["id"], "duration": fit["duration"], "resolution": fit["resolution"],
                    "aspect": fit["aspect"]})
    return {k: out.get(k) for k in VIDEO_KEYS}


def clean_attachments(value: Any, *, limit: int = MAX_DRAFT_ATTACHMENTS) -> list[dict]:
    """``[{file_id, role}]``: ids as ints, duplicates dropped, order kept."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "A list of attachments is expected")
    out: list[dict] = []
    seen: set[int] = set()
    for item in value:
        raw = item.get("file_id") if isinstance(item, dict) else item
        try:
            file_id = int(raw)
        except (TypeError, ValueError):
            continue
        if file_id <= 0 or file_id in seen:
            continue
        seen.add(file_id)
        role = str(item.get("role") or "") if isinstance(item, dict) else ""
        out.append({"file_id": file_id, "role": role})
    if len(out) > limit:
        raise AppError("chat_too_many_attachments", 400, "Too many pictures", max=limit, count=len(out))
    return out


def clean_draft(patch: Any, current: dict) -> dict:
    if not isinstance(patch, dict):
        raise AppError("bad_request", 400, "The draft must be an object")
    out = {**default_draft(), **(current or {})}
    if "text" in patch:
        out["text"] = str(patch["text"] or "").replace("\r\n", "\n")[:MAX_DRAFT]
    if "attachments" in patch:
        out["attachments"] = clean_attachments(patch["attachments"])
    if "reply_to" in patch:
        out["reply_to"] = int(patch["reply_to"]) if patch["reply_to"] else None
        if not out["reply_to"]:
            out["reply_index"] = 0
    if "reply_index" in patch:
        out["reply_index"] = _int(patch["reply_index"] or 0, "reply_index", 0, MAX_FRAMES - 1)
    if "enhance" in patch:
        out["enhance"] = bool(patch["enhance"])
    # video_run_id is set by the server only (POST /chats/{id}/video-draft)
    return out


def _mode(value: Any) -> str:
    mode = str(value or "")
    if mode not in MODES:
        raise AppError("bad_request", 400, "Unknown mode", mode=mode, allowed=list(MODES))
    return mode


def _kit(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    return brand.snapshot_kit(int(value))["kit_id"]


def clean_title(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_TITLE]


def auto_title(text: str) -> str:
    """The first words of the first request (no AI)."""
    words = " ".join(str(text or "").split()).split(" ")
    title = " ".join(words[:TITLE_WORDS]).strip()
    if len(title) > TITLE_CHARS:
        title = title[:TITLE_CHARS].rstrip() + "…"
    elif len(words) > TITLE_WORDS:
        title += "…"
    return title


# ── rows ────────────────────────────────────────────────────────────────────

def chat_row(chat_id: int) -> dict:
    row = db.get("chats", int(chat_id))
    if row is None:
        raise NotFound("chat", id=chat_id)
    return row


def image_settings(chat: dict) -> dict:
    out = default_image_settings()
    out.update(chat.get("image_settings_json") or {})
    return out


def video_settings(chat: dict) -> dict:
    out = default_video_settings()
    saved = chat.get("video_settings_json") or {}
    out.update({k: v for k, v in saved.items() if v is not None or k not in out})
    return out


def draft(chat: dict) -> dict:
    return {**default_draft(), **(chat.get("draft_json") or {})}


def touch(chat_id: int, *, message: bool = False) -> None:
    now = db.now()
    values = {"updated_at": now}
    if message:
        values["last_message_at"] = now
    db.update("chats", chat_id, values)


# ── chats ───────────────────────────────────────────────────────────────────

def create_chat(data: dict | None = None) -> dict:
    data = data or {}
    if not isinstance(data, dict):
        raise AppError("bad_request", 400, "An object is expected")
    kind = str(data.get("kind") or "normal")
    if kind not in KINDS:
        raise AppError("bad_request", 400, "Unknown chat kind", kind=kind, allowed=list(KINDS))
    now = db.now()
    image = default_image_settings()
    video = default_video_settings()
    if data.get("image_settings"):
        image = clean_image_settings(data["image_settings"], image)
    if data.get("video_settings"):
        video = clean_video_settings(data["video_settings"], video)
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    chat_id = db.insert("chats", {
        "title": clean_title(data.get("title")), "title_auto": 0 if clean_title(data.get("title")) else 1,
        "kind": kind, "kit_id": _kit(data.get("kit_id")), "mode": _mode(data.get("mode") or "image"),
        "image_settings_json": image, "video_settings_json": video, "draft_json": default_draft(),
        "meta_json": meta, "created_at": now, "updated_at": now,
    })
    publish(chat_id, what="chat")
    return chat_row(chat_id)


def update_chat(chat_id: int, data: dict) -> dict:
    """Title, mode, brand kit, settings (partial), draft (partial)."""
    if not isinstance(data, dict):
        raise AppError("bad_request", 400, "An object is expected")
    chat = chat_row(chat_id)
    values: dict[str, Any] = {}
    if "title" in data:
        values["title"] = clean_title(data["title"])
        values["title_auto"] = 0 if values["title"] else 1
    if "mode" in data:
        values["mode"] = _mode(data["mode"])
    if "kit_id" in data:
        values["kit_id"] = _kit(data["kit_id"])
    if "image_settings" in data:
        values["image_settings_json"] = clean_image_settings(data["image_settings"], image_settings(chat))
    if "video_settings" in data:
        values["video_settings_json"] = clean_video_settings(data["video_settings"], video_settings(chat))
    if "draft" in data:
        values["draft_json"] = clean_draft(data["draft"], draft(chat))
    if values:
        values["updated_at"] = db.now()
        db.update("chats", chat_id, values)
        if set(values) - {"draft_json", "updated_at"}:
            publish(chat_id, what="chat")
    return chat_row(chat_id)


def set_draft_run(chat_id: int, run_id: int | None) -> None:
    chat = chat_row(chat_id)
    d = draft(chat)
    d["video_run_id"] = run_id
    db.update("chats", chat_id, {"draft_json": d})


def archive_chat(chat_id: int, archived: bool = True) -> dict:
    chat_row(chat_id)
    db.update("chats", chat_id, {"archived_at": db.now() if archived else None, "updated_at": db.now()})
    publish(chat_id, what="chat")
    return chat_row(chat_id)


def list_chats(*, q: str | None = None, archived: bool = False, limit: int = 50, offset: int = 0) -> dict:
    """Recent first. ``q`` looks in titles and in the texts of requests."""
    where = ["c.archived_at IS NOT NULL" if archived else "c.archived_at IS NULL"]
    params: list[Any] = []
    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append("(c.title LIKE ? OR EXISTS (SELECT 1 FROM chat_messages m WHERE m.chat_id = c.id "
                     "AND m.type = 'request' AND m.text LIKE ?))")
        params += [like, like]
    sql_where = " AND ".join(where)
    total = db.fetch_value(f"SELECT COUNT(*) FROM chats c WHERE {sql_where}", params, 0)
    rows = db.fetch_all(
        f"SELECT c.* FROM chats c WHERE {sql_where} "
        "ORDER BY COALESCE(c.last_message_at, c.created_at) DESC, c.id DESC LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)])
    return {"items": [list_item(r) for r in rows], "total": int(total or 0)}


def list_item(chat: dict) -> dict:
    from vf.core import files

    cover = db.fetch_value(
        "SELECT r.ref_id FROM chat_result_refs r JOIN chat_messages m ON m.id = r.message_id "
        "WHERE r.chat_id = ? AND r.ref_type = 'frame' ORDER BY m.position DESC LIMIT 1", (chat["id"],))
    thumb = None
    if cover:
        file_id = db.fetch_value("SELECT file_id FROM frames WHERE id = ?", (cover,))
        thumb = files.url(file_id, w=160) if file_id else None
    return {"id": chat["id"], "title": chat["title"], "kind": chat["kind"], "mode": chat["mode"],
            "archived": bool(chat.get("archived_at")), "thumb_url": thumb,
            "last_message_at": chat.get("last_message_at"), "created_at": chat["created_at"],
            "updated_at": chat["updated_at"], "link": f"/chat/{chat['id']}"}
