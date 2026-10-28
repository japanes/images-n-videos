"""Works and frames: storage, checks of what the browser sends, the view sent back.

A work is a set of frames with shared settings (brand, model, aspect, size,
references, subjects, photo style). A frame is one picture
with its own brief, its overrides of the work settings, and its versions.
"""

from __future__ import annotations

import copy
from typing import Any

from vf.core import db, models_registry
from vf.core.errors import AppError, NotFound
from vf.core.google import journal
from vf.modules import brand, library
from vf.modules.studio.common import (
    ASPECTS,
    BUSY,
    MAX_BRIEF,
    MAX_FEEDBACK,
    MAX_FRAMES,
    MAX_PICKED,
    MAX_TEXT_BLOCKS,
    MAX_TITLE,
    MAX_WORDS,
    SOURCES,
    TEXT_ROLES,
    clean_block,
    clean_text,
    file_brief,
    file_ids,
    publish,
)

IMAGE_SIZES = ("1K", "2K", "4K")
REF_WORK = "work"   # journal refs (spend screen links back to these; names as in spend.json)
REF_FRAME = "frame"

DEFAULT_SETTINGS: dict[str, Any] = {
    "references": [],          # file ids: the work's own reference pictures
    "subjects": [],            # brand subject ids
    "photo_style": None,       # library photo style id; None = plain photo
    "kit_references": True,    # add the brand kit's reference pictures to the references
    "ideas_brief": "",         # the brief of the whole work (frames without their own brief use it)
    "series": False,           # first frame is a pilot; the rest follow its look once it is accepted
    "pilot_frame_id": None,
    "pilot_accepted": False,
    "feedback": "",            # "what to change" for the next generation of every frame
}
OVERRIDE_KEYS = ("model_id", "image_size", "feedback", "references", "subjects", "photo_style", "attachments")


# ── rows ────────────────────────────────────────────────────────────────────

def work_row(work_id: int) -> dict:
    row = db.get("image_works", int(work_id))
    if row is None:
        raise NotFound("work", id=work_id)
    return row


def frame_row(frame_id: int) -> dict:
    row = db.get("frames", int(frame_id))
    if row is None:
        raise NotFound("frame", id=frame_id)
    return row


def frames_of(work_id: int) -> list[dict]:
    return db.fetch_all("SELECT * FROM frames WHERE work_id = ? ORDER BY position, id", (work_id,))


def settings_of(work: dict) -> dict:
    """Saved settings over the defaults; keys no longer in use (an older version) are left out."""
    out = copy.deepcopy(DEFAULT_SETTINGS)
    out.update({k: v for k, v in (work.get("settings_json") or {}).items() if k in DEFAULT_SETTINGS})
    return out


def touch(work_id: int) -> None:
    db.update("image_works", work_id, {"updated_at": db.now()})


def _new_frame(work_id: int, position: int) -> int:
    now = db.now()
    return db.insert("frames", {"work_id": work_id, "position": position, "created_at": now, "updated_at": now})


def _renumber(work_id: int) -> None:
    for index, row in enumerate(frames_of(work_id)):
        if row["position"] != index:
            db.update("frames", row["id"], {"position": index})


# ── checks of what the browser sends ────────────────────────────────────────

def _image_model(model_id: Any) -> dict:
    return models_registry.resolve("image", str(model_id))


def _image_size(value: Any) -> str:
    size = str(value or "")
    if size not in IMAGE_SIZES:
        raise AppError("bad_size", 400, "Unknown picture size", size=size, allowed=list(IMAGE_SIZES))
    return size


def _photo_style(value: Any) -> Any:
    if value is None or value == "":
        return None
    if library.photo_style_text(value) is None:
        raise AppError("bad_style", 400, "This photo style is not in the library", style=value)
    return value


def _subjects(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "A list of subjects is expected")
    return brand.normalize_subject_ids(value, MAX_PICKED)


def text_blocks(value: Any) -> list[dict]:
    """``[{role: headline|body|accent, text}]``: empty blocks dropped."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError("bad_request", 400, "A list of text blocks is expected")
    out = []
    for item in value:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = clean_block(item.get("text"), MAX_WORDS)
        if not text:
            continue
        role = item.get("role") if item.get("role") in TEXT_ROLES else "body"
        out.append({"role": role, "text": text})
    if len(out) > MAX_TEXT_BLOCKS:
        raise AppError("too_many_text_blocks", 400, "Too many text blocks", max=MAX_TEXT_BLOCKS)
    return out


def clean_settings(patch: Any, current: dict) -> dict:
    """Merge a partial settings change into ``current`` (keys left out stay)."""
    if not isinstance(patch, dict):
        raise AppError("bad_request", 400, "Settings must be an object")
    out = copy.deepcopy(current)
    for key, value in patch.items():
        if key == "references":
            out[key] = file_ids(value)
        elif key == "subjects":
            out[key] = _subjects(value)
        elif key == "photo_style":
            out[key] = _photo_style(value)
        elif key == "kit_references":
            out[key] = bool(value)
        elif key == "ideas_brief":
            out[key] = clean_block(value, MAX_BRIEF)
        elif key == "feedback":
            out[key] = clean_block(value, MAX_FEEDBACK)
        elif key == "series":
            out[key] = bool(value)
            if not out[key]:
                out["pilot_frame_id"] = None
                out["pilot_accepted"] = False
        # pilot_* and unknown keys are not set from outside
    return out


def clean_overrides(value: Any) -> dict:
    """A frame's own settings. A key that is present overrides the work; a key left
    out inherits. ``null``/"" drop the plain ones; ``[]`` means "none" for
    references and subjects; ``null`` photo style means a plain photo."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AppError("bad_request", 400, "Overrides must be an object")
    out: dict[str, Any] = {}
    for key in OVERRIDE_KEYS:
        if key not in value:
            continue
        raw = value[key]
        if key == "model_id":
            if raw:
                out[key] = _image_model(raw)["id"]
        elif key == "image_size":
            if raw:
                out[key] = _image_size(raw)
        elif key == "feedback":
            text = clean_block(raw, MAX_FEEDBACK)
            if text:
                out[key] = text
        elif key == "references":
            out[key] = file_ids(raw or [])
        elif key == "subjects":
            out[key] = _subjects(raw or [])
        elif key == "photo_style":
            out[key] = _photo_style(raw)
        elif key == "attachments":
            ids = file_ids(raw or [])
            if ids:
                out[key] = ids
    return out


# ── what a frame is made with ───────────────────────────────────────────────

def pick_size(model: dict, wanted: str) -> str:
    """The size if the model makes it; else 1K when it does; else its first size."""
    allowed = list((model.get("caps") or {}).get("allowed_resolutions") or ["1K"])
    if wanted in allowed:
        return wanted
    return "1K" if "1K" in allowed else allowed[0]


def effective(work: dict, frame: dict) -> dict:
    """The settings a frame is generated with: its overrides over the work.

    Raises the registry's errors (model_disabled, no_model…) when the model cannot be used."""
    s = settings_of(work)
    ov = frame.get("overrides_json") or {}
    model = models_registry.resolve("image", ov.get("model_id") or work.get("model_id"))
    wanted = ov.get("image_size") or work.get("image_size") or "1K"
    size = pick_size(model, wanted)
    references = list(ov["references"] if "references" in ov else s["references"])
    snap = work.get("brand_json")
    if s["kit_references"] and snap:
        for ref in snap.get("references") or []:
            if ref.get("file_id") and ref["file_id"] not in references:
                references.append(ref["file_id"])
    return {
        "model": model,
        "model_id": model["id"],
        "image_size": size,
        "size_wanted": wanted,
        "references": references,
        "subjects": list(ov["subjects"] if "subjects" in ov else s["subjects"]),
        "photo_style": ov["photo_style"] if "photo_style" in ov else s["photo_style"],
        "feedback": ov.get("feedback") or s["feedback"],
        "attachments": list(ov.get("attachments") or []),
    }


def is_pilot(work: dict, frame: dict) -> bool:
    s = settings_of(work)
    return bool(s["series"]) and frame["position"] == 0


def pilot_frame(work: dict) -> dict | None:
    """The first frame of a series (None when the work is not a series)."""
    if not settings_of(work)["series"]:
        return None
    rows = frames_of(work["id"])
    return rows[0] if rows else None


def anchor_file(work: dict, frame: dict) -> int | None:
    """The pilot's picture, sent to the other frames of an accepted series."""
    s = settings_of(work)
    if not (s["series"] and s["pilot_accepted"]) or frame["position"] == 0:
        return None
    pilot = pilot_frame(work)
    if pilot is None or pilot["id"] == frame["id"] or not pilot.get("file_id"):
        return None
    return pilot["file_id"]


# ── the view sent to the browser ────────────────────────────────────────────

def _waiting(frame: dict) -> bool:
    """Google asked to wait (rate limit) and the gateway is pausing before the next try."""
    if frame["status"] != "drawing":
        return False
    row = db.fetch_one(
        "SELECT c.status, c.error_code FROM ai_calls c JOIN ai_call_refs r ON r.call_id = c.id "
        "WHERE r.ref_type = ? AND r.ref_id = ? ORDER BY c.id DESC LIMIT 1", (REF_FRAME, frame["id"]))
    return bool(row and row["status"] == "error" and row["error_code"] == "rate_limited")


def _versions(frame: dict) -> list[dict]:
    out = []
    for index, v in enumerate(frame.get("versions_json") or []):
        out.append({
            "index": index, "file": file_brief(v.get("file_id")), "at": v.get("at"), "mode": v.get("mode"),
            "source": v.get("source"), "cost_usd": v.get("cost_usd") or 0, "model_id": v.get("model_id"),
            "image_size": v.get("image_size"), "prompt_text": v.get("prompt_text"),
            "current": bool(v.get("file_id")) and v.get("file_id") == frame.get("file_id"),
        })
    return out


def _attachments(frame: dict) -> list[dict]:
    out = []
    for a in frame.get("attachments_json") or []:
        brief = file_brief(a.get("file_id")) if a.get("file_id") else None
        out.append({**a, "url": brief["url"] if brief else None, "thumb_url": brief["thumb_url"] if brief else None})
    return out


def current_objects(frame: dict) -> dict | None:
    """Found objects, only when they were found on the picture the frame shows now."""
    data = frame.get("objects_json")
    if not data or not frame.get("file_id"):
        return None
    row = db.get("files", frame["file_id"])
    if row is None or not row.get("sha256") or row["sha256"] != data.get("sha"):
        return None
    return data


def frame_public(frame: dict, work: dict | None = None) -> dict:
    work = work or work_row(frame["work_id"])
    out = {
        "id": frame["id"], "work_id": frame["work_id"], "position": frame["position"], "brief": frame["brief"],
        "overrides": frame.get("overrides_json") or {}, "status": frame["status"], "waiting": _waiting(frame),
        "file": file_brief(frame.get("file_id")), "file_id": frame.get("file_id"),
        "clean_file_id": frame.get("clean_file_id"), "source": frame["source"],
        "source_ref": frame.get("source_ref_json"), "prompt_text": frame.get("prompt_text"),
        "attachments": _attachments(frame), "text_blocks": frame.get("text_blocks_json") or [],
        "objects": None, "versions": _versions(frame), "job_id": frame.get("job_id"),
        "error_code": frame.get("error_code"), "error_text": frame.get("error_text"),
        "drawing_since": frame.get("drawing_since"), "cost_usd": round(frame.get("cost_usd") or 0, 6),
        "is_pilot": is_pilot(work, frame), "effective": None,
        "created_at": frame["created_at"], "updated_at": frame["updated_at"],
    }
    found = current_objects(frame)
    if found:
        out["objects"] = {"items": found.get("items") or [], "focus": found.get("focus") or "",
                          "at": found.get("at"), "cost_usd": found.get("cost_usd") or 0}
    try:
        eff = effective(work, frame)
    except AppError as exc:
        out["effective"] = {"error": exc.code}
        return out
    out["effective"] = {k: v for k, v in eff.items() if k != "model"}
    out["effective"]["model_title"] = eff["model"].get("title")
    return out


def work_public(work: dict, *, with_frames: bool = True) -> dict:
    s = settings_of(work)
    snap = work.get("brand_json")
    out = {
        "id": work["id"], "title": work["title"], "kit_id": work.get("kit_id"), "brand": snap,
        "kit_changed": brand.kit_changed(snap) if snap else None, "model_id": work.get("model_id"),
        "aspect": work["aspect"], "image_size": work["image_size"], "frame_count": work["frame_count"],
        "settings": s, "status": work["status"], "archived_at": work.get("archived_at"),
        "created_at": work["created_at"], "updated_at": work["updated_at"],
        "cost_usd": round(journal.cost_of(REF_WORK, work["id"]), 6),
    }
    if with_frames:
        rows = frames_of(work["id"])
        out["frames"] = [frame_public(f, work) for f in rows]
        pilot = rows[0] if s["series"] and rows else None
        out["pilot"] = {
            "frame_id": pilot["id"] if pilot else None,
            "accepted": bool(s["pilot_accepted"]),
            "ready": bool(pilot and pilot["status"] == "done" and pilot.get("file_id")),
        }
    return out


# ── works ───────────────────────────────────────────────────────────────────

def _check_kit(kit_id: Any) -> tuple[int | None, dict | None]:
    if kit_id in (None, "", 0):
        return None, None
    snap = brand.snapshot_kit(int(kit_id))
    return snap["kit_id"], snap


def create_work(data: dict | None = None) -> dict:
    data = data or {}
    now = db.now()
    values: dict[str, Any] = {"title": clean_text(data.get("title"), MAX_TITLE), "created_at": now, "updated_at": now,
                              "settings_json": clean_settings(data.get("settings") or {}, copy.deepcopy(DEFAULT_SETTINGS))}
    if data.get("model_id"):
        values["model_id"] = _image_model(data["model_id"])["id"]
    if data.get("aspect"):
        values["aspect"] = _aspect(data["aspect"])
    if data.get("image_size"):
        values["image_size"] = _image_size(data["image_size"])
    count = _frame_count(data.get("frame_count", 1))
    values["frame_count"] = count
    values["kit_id"], values["brand_json"] = _check_kit(data.get("kit_id"))
    with db.tx():
        work_id = db.insert("image_works", values)
        for position in range(count):
            _new_frame(work_id, position)
    publish("work", work_id=work_id)
    return get_work(work_id)


def _aspect(value: Any) -> str:
    aspect = str(value or "")
    if aspect not in ASPECTS:
        raise AppError("bad_aspect", 400, "Unknown aspect ratio", aspect=aspect, allowed=list(ASPECTS))
    return aspect


def _frame_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise AppError("too_many_frames", 400, "The number of frames is from 1 to 10", max=MAX_FRAMES) from None
    if not 1 <= count <= MAX_FRAMES:
        raise AppError("too_many_frames", 400, "The number of frames is from 1 to 10", max=MAX_FRAMES)
    return count


def get_work(work_id: int) -> dict:
    return work_public(work_row(work_id))


def list_works(*, status: str = "active", q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """``status``: active (drafts and works with pictures), archived, all."""
    where, params = [], []
    if status == "archived":
        where.append("w.status = 'archived'")
    elif status != "all":
        where.append("w.status != 'archived'")
    if q:
        where.append("w.title LIKE ?")
        params.append(f"%{q.strip()}%")
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.fetch_value(f"SELECT COUNT(*) FROM image_works w {sql_where}", params, 0)
    rows = db.fetch_all(
        f"SELECT w.*, (SELECT COUNT(*) FROM frames f WHERE f.work_id = w.id AND f.file_id IS NOT NULL) AS done_count, "
        f"(SELECT COALESCE(SUM(f.cost_usd), 0) FROM frames f WHERE f.work_id = w.id) AS frames_cost, "
        f"(SELECT f.file_id FROM frames f WHERE f.work_id = w.id AND f.file_id IS NOT NULL "
        f" ORDER BY f.position, f.id LIMIT 1) AS cover_id "
        f"FROM image_works w {sql_where} ORDER BY w.updated_at DESC, w.id DESC LIMIT ? OFFSET ?",
        [*params, max(1, min(int(limit), 200)), max(0, int(offset))])
    items = [{
        "id": r["id"], "title": r["title"], "status": r["status"], "aspect": r["aspect"],
        "frame_count": r["frame_count"], "done_count": r["done_count"], "cover": file_brief(r["cover_id"]),
        "cost_usd": round(r["frames_cost"] or 0, 6), "kit_name": (r.get("brand_json") or {}).get("name"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    } for r in rows]
    return {"items": items, "total": total}


def _busy_frames(work_id: int) -> list[dict]:
    return db.fetch_all("SELECT id FROM frames WHERE work_id = ? AND status IN ('queued', 'drawing')", (work_id,))


def update_work(work_id: int, data: dict) -> dict:
    """Change title, brand, model, aspect, size, frame count and settings (partial)."""
    if not isinstance(data, dict):
        raise AppError("bad_request", 400, "An object is expected")
    work = work_row(work_id)
    values: dict[str, Any] = {}
    if "title" in data:
        values["title"] = clean_text(data["title"], MAX_TITLE)
    if "kit_id" in data:
        values["kit_id"], values["brand_json"] = _check_kit(data["kit_id"])
    if "model_id" in data:
        values["model_id"] = _image_model(data["model_id"])["id"] if data["model_id"] else None
    if "aspect" in data:
        values["aspect"] = _aspect(data["aspect"])
    if "image_size" in data:
        values["image_size"] = _image_size(data["image_size"])
    if "settings" in data:
        values["settings_json"] = clean_settings(data["settings"], settings_of(work))
    with db.tx():
        if "frame_count" in data:
            set_frame_count(work, _frame_count(data["frame_count"]))
        if values:
            values["updated_at"] = db.now()
            db.update("image_works", work_id, values)
    publish("work", work_id=work_id)
    return get_work(work_id)


def refresh_brand(work_id: int) -> dict:
    """Take a fresh copy of the kit (after it was edited)."""
    work = work_row(work_id)
    if not work.get("kit_id"):
        raise AppError("no_kit", 409, "The work has no brand kit")
    _, snap = _check_kit(work["kit_id"])
    db.update("image_works", work_id, {"brand_json": snap, "updated_at": db.now()})
    publish("work", work_id=work_id)
    return get_work(work_id)


def archive_work(work_id: int, archived: bool = True) -> dict:
    work = work_row(work_id)
    if archived:
        values = {"status": "archived", "archived_at": db.now()}
    else:
        has_pictures = db.fetch_value("SELECT COUNT(*) FROM frames WHERE work_id = ? AND file_id IS NOT NULL",
                                      (work_id,), 0)
        values = {"status": "active" if has_pictures else "draft", "archived_at": None}
    if work["status"] == values["status"]:
        return get_work(work_id)
    values["updated_at"] = db.now()
    db.update("image_works", work_id, values)
    publish("work", work_id=work_id)
    return get_work(work_id)


def delete_work(work_id: int) -> None:
    """Remove the work and its frames. The pictures stay in the media library."""
    work_row(work_id)
    if _busy_frames(work_id):
        raise AppError("frame_busy", 409, "A frame is being drawn; stop it first")
    db.delete("image_works", work_id)
    publish("work", work_id=work_id, deleted=True)


# ── frames ──────────────────────────────────────────────────────────────────

def set_frame_count(work: dict, count: int) -> None:
    """Add empty frames at the end or remove the last ones (call inside ``db.tx``)."""
    rows = frames_of(work["id"])
    if count > len(rows):
        for position in range(len(rows), count):
            _new_frame(work["id"], position)
    elif count < len(rows):
        dropped = rows[count:]
        if any(r["status"] in BUSY for r in dropped):
            raise AppError("frame_busy", 409, "A frame is being drawn; stop it first")
        for r in dropped:
            db.delete("frames", r["id"])
        _fix_pilot(work, removed={r["id"] for r in dropped})
    db.update("image_works", work["id"], {"frame_count": count, "updated_at": db.now()})


def _fix_pilot(work: dict, removed: set[int]) -> None:
    s = settings_of(work)
    if s.get("pilot_frame_id") in removed:
        s["pilot_frame_id"] = None
        s["pilot_accepted"] = False
        db.update("image_works", work["id"], {"settings_json": s})


def add_frame(work_id: int, *, after: int | None = None) -> dict:
    """A new empty frame at the end, or right after frame ``after``."""
    work = work_row(work_id)
    rows = frames_of(work_id)
    if len(rows) >= MAX_FRAMES:
        raise AppError("too_many_frames", 400, "The number of frames is from 1 to 10", max=MAX_FRAMES)
    with db.tx():
        position = len(rows)
        if after is not None:
            index = next((i for i, r in enumerate(rows) if r["id"] == int(after)), None)
            if index is None:
                raise NotFound("frame", id=after)
            position = index + 1
            for r in rows[position:]:
                db.update("frames", r["id"], {"position": r["position"] + 1})
        frame_id = _new_frame(work_id, position)
        _renumber(work_id)
        db.update("image_works", work_id, {"frame_count": len(rows) + 1, "updated_at": db.now()})
    publish("work", work_id=work_id)
    return frame_public(frame_row(frame_id), work_row(work["id"]))


def delete_frame(frame_id: int) -> dict:
    frame = frame_row(frame_id)
    work = work_row(frame["work_id"])
    rows = frames_of(work["id"])
    if len(rows) <= 1:
        raise AppError("last_frame", 409, "A work keeps at least one frame")
    if frame["status"] in BUSY:
        raise AppError("frame_busy", 409, "The frame is being drawn; stop it first")
    with db.tx():
        db.delete("frames", frame_id)
        _renumber(work["id"])
        _fix_pilot(work, {frame_id})
        db.update("image_works", work["id"], {"frame_count": len(rows) - 1, "updated_at": db.now()})
    publish("work", work_id=work["id"])
    return get_work(work["id"])


def reorder_frames(work_id: int, ids: list[int]) -> dict:
    """New order of all frames (the first one becomes the pilot of a series)."""
    work = work_row(work_id)
    rows = frames_of(work_id)
    if sorted(ids) != sorted(r["id"] for r in rows):
        raise AppError("bad_order", 400, "The list must name every frame of the work once")
    if settings_of(work)["series"] and ids[0] != rows[0]["id"] and any(r["status"] in BUSY for r in rows):
        raise AppError("frame_busy", 409, "A frame is being drawn; stop it first")
    with db.tx():
        for position, frame_id in enumerate(ids):
            db.update("frames", frame_id, {"position": position})
        if settings_of(work)["series"] and ids[0] != rows[0]["id"]:
            s = settings_of(work)
            s["pilot_frame_id"], s["pilot_accepted"] = None, False
            db.update("image_works", work_id, {"settings_json": s})
        touch(work_id)
    publish("work", work_id=work_id)
    return get_work(work_id)


def update_frame(frame_id: int, data: dict) -> dict:
    """Brief, overrides (the whole dict) and the words for the picture."""
    if not isinstance(data, dict):
        raise AppError("bad_request", 400, "An object is expected")
    frame = frame_row(frame_id)
    values: dict[str, Any] = {}
    if "brief" in data:
        values["brief"] = clean_block(data["brief"], MAX_BRIEF)
    if "overrides" in data:
        values["overrides_json"] = clean_overrides(data["overrides"])
    if "text_blocks" in data:
        values["text_blocks_json"] = text_blocks(data["text_blocks"])
    if values:
        values["updated_at"] = db.now()
        db.update("frames", frame_id, values)
        touch(frame["work_id"])
        publish("frame", work_id=frame["work_id"], frame_id=frame_id, status=frame["status"])
    return frame_public(frame_row(frame_id))


def check_source(value: Any) -> str:
    source = str(value or "")
    if source not in SOURCES:
        raise AppError("bad_request", 400, "Unknown picture source", source=source)
    return source
