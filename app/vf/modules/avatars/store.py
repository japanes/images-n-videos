"""Avatars and their pictures: rows, the views the browser gets, the list.

One avatar = one row in ``avatars`` plus its pictures in ``avatar_photos``:
  source     photos the person uploaded (up to 12; marked ones go with every shot)
  candidate  face candidates drawn from the identity
  face       the chosen face (history: the old ones are archived)
  shot       the 36 slots of the pack, created up front; SHOT_01 is the face
"""

from __future__ import annotations

from typing import Any

from vf.core import db, files, jobs, models_registry
from vf.core.errors import AppError, NotFound
from vf.core.google import journal
from vf.modules.avatars import catalog
from vf.modules.avatars.common import (
    BUSY,
    DEFAULT_CANDIDATES,
    FACE_CODE,
    KIND_CARD,
    MAX_BRIEF,
    MAX_CANDIDATES,
    MAX_NAME,
    MIN_CANDIDATES,
    MODES,
    REF_AVATAR,
    clean_lines,
    clean_text,
    publish,
)

STATES = ("no_identity", "no_face", "face_ready", "unfinished", "ready")


# ── rows ────────────────────────────────────────────────────────────────────

def avatar_row(avatar_id: Any) -> dict:
    try:
        row = db.get("avatars", int(avatar_id))
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise NotFound("avatar", id=avatar_id)
    return row


def photo_row(photo_id: Any) -> dict:
    try:
        row = db.get("avatar_photos", int(photo_id))
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise NotFound("avatar_photo", id=photo_id)
    return row


def touch(avatar_id: int, values: dict | None = None) -> None:
    db.update("avatars", avatar_id, {**(values or {}), "updated_at": db.now()})


def set_photo(photo_id: int, values: dict) -> None:
    values["updated_at"] = db.now()
    db.update("avatar_photos", photo_id, values)


def photos_of(avatar_id: int, kind: str | None = None, *, archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM avatar_photos WHERE avatar_id = ?"
    params: list[Any] = [avatar_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if not archived:
        sql += " AND status != 'archived'"
    return db.fetch_all(sql + " ORDER BY sort, id", params)


def sources_of(avatar_id: int) -> list[dict]:
    return [p for p in photos_of(avatar_id, "source") if p.get("file_id")]


def slots_of(avatar_id: int) -> list[dict]:
    """The 36 shot slots in pack order (rows missing from an older avatar are created)."""
    rows = {r["shot_code"]: r for r in photos_of(avatar_id, "shot")}
    if len(rows) < len(catalog.codes()):
        ensure_slots(avatar_id)
        rows = {r["shot_code"]: r for r in photos_of(avatar_id, "shot")}
    return [rows[code] for code in catalog.codes() if code in rows]


def slot(avatar_id: int, code: str) -> dict | None:
    return db.fetch_one("SELECT * FROM avatar_photos WHERE avatar_id = ? AND kind = 'shot' AND shot_code = ?",
                        (avatar_id, code))


def ensure_slots(avatar_id: int) -> None:
    have = {r["shot_code"] for r in db.fetch_all(
        "SELECT shot_code FROM avatar_photos WHERE avatar_id = ? AND kind = 'shot'", (avatar_id,))}
    now = db.now()
    for s in catalog.shots():
        if s["code"] in have:
            continue
        db.insert("avatar_photos", {"avatar_id": avatar_id, "kind": "shot", "shot_code": s["code"],
                                    "title": s["title"], "sort": int(s.get("sort") or 0), "status": "empty",
                                    "origin": "generated", "created_at": now, "updated_at": now})


def face_row(avatar_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM avatar_photos WHERE avatar_id = ? AND kind = 'face' AND status != 'archived' "
                        "ORDER BY id DESC LIMIT 1", (avatar_id,))


# ── views ───────────────────────────────────────────────────────────────────

def file_card(file_id: int | None) -> dict | None:
    """id, urls, size; None when the file is gone."""
    if not file_id:
        return None
    try:
        row = files.get(file_id)
    except AppError:
        return None
    return {"id": row["id"], "url": files.url(row["id"]), "thumb_url": files.url(row["id"], w=480),
            "width": row.get("width"), "height": row.get("height"), "mime": row["mime"],
            "title": row.get("title") or row.get("original_name")}


def photo_public(row: dict) -> dict:
    meta = row.get("meta_json") or {}
    return {
        "id": row["id"], "avatar_id": row["avatar_id"], "kind": row["kind"], "shot_code": row.get("shot_code"),
        "title": row.get("title") or "", "angle": row.get("angle") or "", "marked": bool(row.get("marked")),
        "sort": row.get("sort") or 0, "custom_prompt": row.get("custom_prompt"),
        "prompt_text": row.get("prompt_text"), "origin": row.get("origin"), "message_id": row.get("message_id"),
        "status": row["status"], "job_id": row.get("job_id"), "error_code": row.get("error_code"),
        "error_text": row.get("error_text"), "cost_usd": round(float(row.get("cost_usd") or 0), 6),
        "meta": meta, "file": file_card(row.get("file_id")), "file_id": row.get("file_id"),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _job_active(job_id: Any) -> bool:
    if not job_id:
        return False
    job = db.get("jobs", int(job_id))
    return job is not None and job["status"] in jobs.ACTIVE


def counts(avatar: dict, slots: list[dict] | None = None) -> dict:
    slots = slots if slots is not None else slots_of(avatar["id"])
    done = sum(1 for s in slots if s.get("file_id"))
    busy = sum(1 for s in slots if s["status"] in BUSY)
    failed = sum(1 for s in slots if s["status"] == "error" and not s.get("file_id"))
    empty = sum(1 for s in slots if not s.get("file_id") and s["status"] not in BUSY
                and s.get("shot_code") != FACE_CODE)
    return {"done": done, "total": len(catalog.codes()), "busy": busy, "failed": failed, "empty": empty}


def state_of(avatar: dict, slots: list[dict] | None = None) -> str:
    """no_identity → no_face → face_ready → unfinished → ready."""
    if not (avatar.get("identity") or "").strip():
        return "no_identity"
    if not avatar.get("face_file_id"):
        return "no_face"
    slots = slots if slots is not None else slots_of(avatar["id"])
    c = counts(avatar, slots)
    if c["done"] >= c["total"]:
        return "ready"
    started = any(s.get("shot_code") != FACE_CODE and (s["status"] in (*BUSY, "error") or s.get("file_id"))
                  for s in slots)
    return "unfinished" if started else "face_ready"


def _busy_any(avatar_id: int) -> bool:
    return bool(db.fetch_value("SELECT 1 FROM avatar_photos WHERE avatar_id = ? AND status IN ('queued', 'drawing') "
                               "LIMIT 1", (avatar_id,), default=None))


def summary(row: dict) -> dict:
    """A line of the list: name, state, N of M, the face."""
    slots = slots_of(row["id"])
    return {
        "id": row["id"], "name": row["name"], "init_mode": row["init_mode"], "state": state_of(row, slots),
        "counts": counts(row, slots), "face": file_card(row.get("face_file_id")),
        "identity_locked": bool(row["identity_locked"]), "chat_id": row.get("chat_id"),
        "message_id": row.get("message_id"), "busy": _busy_any(row["id"]),
        "describing": _job_active(row.get("describe_job_id")), "cost_usd": round(float(row.get("cost_usd") or 0), 6),
        "as_subject": bool(row["as_subject"]), "subject_id": row.get("subject_id"),
        "archived_at": row.get("archived_at"), "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def view(row: dict) -> dict:
    """Everything the avatar chat and the 36-slot grid show."""
    avatar_id = row["id"]
    slots = slots_of(avatar_id)
    shot_info = {s["code"]: s for s in catalog.shots()}
    out = summary(row)
    out.update({
        "brief": row["brief"], "identity": row["identity"], "identity_source": row["identity_source"],
        "image_model_id": row.get("image_model_id"), "candidate_count": int(row["candidate_count"] or 4),
        "describe_job_id": row.get("describe_job_id"), "describe_message_id": row.get("describe_message_id"),
        "sources": [photo_public(p) for p in photos_of(avatar_id, "source")],
        "candidates": [photo_public(p) for p in photos_of(avatar_id, "candidate")],
        "face_photo": (lambda f: photo_public(f) if f else None)(face_row(avatar_id)),
        "slots": [{**photo_public(s), "category": shot_info.get(s["shot_code"], {}).get("category"),
                   "catalog_prompt": shot_info.get(s["shot_code"], {}).get("prompt")} for s in slots],
    })
    return out


def get(avatar_id: Any) -> dict:
    return view(avatar_row(avatar_id))


def list_avatars(*, archived: bool = False) -> dict:
    where = "archived_at IS NOT NULL" if archived else "archived_at IS NULL"
    rows = db.fetch_all(f"SELECT * FROM avatars WHERE {where} ORDER BY updated_at DESC, id DESC")
    return {"items": [summary(r) for r in rows], "total": len(rows)}


def refresh_cost(avatar_id: int) -> float:
    cost = journal.cost_of(REF_AVATAR, avatar_id)
    db.update("avatars", avatar_id, {"cost_usd": cost})
    return cost


def announce(avatar_id: int, **extra: Any) -> None:
    """The card, the grid and the list follow the avatar through this event."""
    row = db.get("avatars", avatar_id)
    if row is None:
        return
    publish("avatar", avatar_id=avatar_id, chat_id=row.get("chat_id"), **extra)


# ── writing ─────────────────────────────────────────────────────────────────

def _mode(value: Any) -> str:
    mode = str(value or "reference")
    if mode not in MODES:
        raise AppError("avatar_mode_unknown", 400, "Unknown way to start the avatar", mode=mode, allowed=list(MODES))
    return mode


def _brief(value: Any) -> str:
    text = clean_lines(str(value or ""))
    if len(text) > MAX_BRIEF:
        raise AppError("avatar_brief_too_long", 400, "The description is too long", max=MAX_BRIEF)
    return text


def _name(value: Any) -> str:
    name = clean_text(value, MAX_NAME)
    if not name:
        raise AppError("avatar_name_required", 400, "Give the avatar a name")
    return name


def _count(value: Any) -> int:
    try:
        return min(max(int(value), MIN_CANDIDATES), MAX_CANDIDATES)
    except (TypeError, ValueError):
        return DEFAULT_CANDIDATES


def _model(value: Any) -> str | None:
    if not value:
        return None
    return models_registry.resolve("image", str(value))["id"]


def create(body: Any) -> dict:
    """``{avatar, chat_id, message_id}``: the avatar, its 36 empty slots, its chat and its card."""
    from vf.modules import chat

    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    name = _name(body.get("name"))
    mode = _mode(body.get("mode") or body.get("init_mode"))
    brief = _brief(body.get("brief"))
    model_id = _model(body.get("image_model_id"))
    now = db.now()
    with db.tx():
        avatar_id = db.insert("avatars", {
            "name": name, "brief": brief, "init_mode": mode, "image_model_id": model_id,
            "candidate_count": _count(body.get("candidate_count", DEFAULT_CANDIDATES)),
            "as_subject": 1, "created_at": now, "updated_at": now,
        })
        ensure_slots(avatar_id)
    c = chat.create_chat({"kind": "avatar", "title": name, "meta": {"avatar_id": avatar_id}})
    message = chat.post_message(c["id"], kind=KIND_CARD, text=name, data={"avatar_id": avatar_id},
                                links=[(REF_AVATAR, avatar_id)])
    touch(avatar_id, {"chat_id": c["id"], "message_id": message["id"]})
    announce(avatar_id, created=True)
    return {"avatar": get(avatar_id), "chat_id": c["id"], "message_id": message["id"]}


def update(avatar_id: Any, body: Any) -> dict:
    """Name, brief, mode, image model, number of candidates, «use as a subject»."""
    from vf.modules import chat
    from vf.modules.avatars import subject

    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    row = avatar_row(avatar_id)
    values: dict[str, Any] = {}
    if "name" in body:
        values["name"] = _name(body["name"])
    if "brief" in body:
        values["brief"] = _brief(body["brief"])
    if "init_mode" in body or "mode" in body:
        values["init_mode"] = _mode(body.get("init_mode", body.get("mode")))
    if "image_model_id" in body:
        values["image_model_id"] = _model(body["image_model_id"])
    if "candidate_count" in body:
        values["candidate_count"] = _count(body["candidate_count"])
    if "as_subject" in body:
        values["as_subject"] = 1 if body["as_subject"] else 0
    if values:
        touch(row["id"], values)
        if "name" in values and row.get("chat_id") and values["name"] != row["name"]:
            try:
                chat.update_chat(row["chat_id"], {"title": values["name"]})
            except AppError:
                pass
        if {"name", "as_subject"} & set(values):
            subject.sync(row["id"])
        announce(row["id"])
    return get(row["id"])


def archive(avatar_id: Any, archived: bool = True) -> dict:
    """Out of the list (and its chat out of the sidebar); nothing is deleted.
    An archived avatar stops being offered as a subject."""
    from vf.modules.avatars import subject
    from vf.modules.chat import store as chat_store

    row = avatar_row(avatar_id)
    touch(row["id"], {"archived_at": db.now() if archived else None})
    if row.get("chat_id"):
        try:
            chat_store.archive_chat(row["chat_id"], archived)
        except AppError:
            pass
    subject.sync(row["id"])
    announce(row["id"])
    return get(row["id"])
