"""The master identity: «Describe» (paid), the manual edit, the lock.

«Describe» is one Gemini call with the role ``vision_describe``: in reference mode
up to 3 photos (marked first, then in the person's order) as 1024 px JPEG, then
the layer AVATAR_IDENTITY_INPUT (mode, number of photos, the brief). The answer is
JSON ``{"identity": "..."}``: 200–6000 characters of English. It runs as a job
("avatar.describe", group "text"), so the answer arrives even if the browser is
closed, and shows up in the avatar chat as an ``avatar.identity`` message.

An existing identity is never replaced silently: without ``force`` the start stops
with ``avatar_identity_exists`` and the browser asks. A locked identity (the face
was chosen from it) is never replaced at all until the person unlocks it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from vf.core import db, files, google, jobs, models_registry, pricing, prompts
from vf.core.errors import AppError
from vf.core.google import GoogleCallError, journal
from vf.modules import library
from vf.modules.avatars import messages, store
from vf.modules.avatars.common import (
    DESCRIBE_MAX_TOKENS,
    DESCRIBE_TEMPERATURE,
    IDENTITY_PHOTOS,
    JOB_DESCRIBE,
    KIND_IDENTITY,
    MAX_IDENTITY,
    MIN_IDENTITY,
    PROMPT_IDENTITY,
    PURPOSE_IDENTITY,
    REF_AVATAR,
    REF_MESSAGE,
    ROLE_DESCRIBE,
    clean_identity,
    clean_lines,
    log,
)

THUMB_SIDE = 1024


# ── what goes to «Describe» ─────────────────────────────────────────────────

def describe_photos(avatar: dict) -> list[dict]:
    """Reference mode: up to 3 uploaded photos, marked first, then in the person's order.
    Other modes send no photos (the person is invented)."""
    if avatar["init_mode"] != "reference":
        return []
    rows = list(store.sources_of(avatar["id"]))
    rows.sort(key=lambda p: (0 if p.get("marked") else 1, p.get("sort") or 0, p["id"]))
    return rows[:IDENTITY_PHOTOS]


def input_text(avatar: dict, photo_count: int) -> str:
    return library.render_layer("AVATAR_IDENTITY_INPUT", {
        "mode": avatar["init_mode"], "photo_count": int(photo_count), "brief": (avatar.get("brief") or "").strip(),
    }).strip()


def describe_model() -> dict:
    """The model of the role «describe a photo» (from settings, never from code)."""
    return models_registry.model_for_role(ROLE_DESCRIBE)


def price(avatar: dict) -> dict:
    """``{usd, model_id, photos}``: what one «Describe» will cost."""
    model = describe_model()
    count = len(describe_photos(avatar))
    usd = pricing.estimate_text(model, purpose=PURPOSE_IDENTITY, input_images=count)
    return {"usd": round(usd, 4), "model_id": model["id"], "photos": count}


def _blobs(rows: list[dict]) -> list[google.Blob]:
    from vf.modules.studio import imaging

    out: list[google.Blob] = []
    for p in rows:
        try:
            row = files.get(p["file_id"])
            data, mime = imaging.shrink(files.read_bytes(p["file_id"]), row["mime"], max_side=THUMB_SIDE)
        except (AppError, OSError):
            continue
        out.append(google.Blob(data, mime, p["file_id"]))
    return out


def _check(avatar: dict, *, force: bool) -> None:
    """Every refusal before money is spent."""
    if avatar.get("identity_locked"):
        raise AppError("avatar_identity_locked", 409, "The description is locked; unlock it first")
    if (avatar.get("identity") or "").strip() and not force:
        raise AppError("avatar_identity_exists", 409, "The avatar already has a description; confirm to replace it")
    if avatar["init_mode"] == "reference" and not store.sources_of(avatar["id"]):
        raise AppError("avatar_no_photos", 409, "Add at least one photo of the person")
    if avatar["init_mode"] == "description" and not (avatar.get("brief") or "").strip():
        raise AppError("avatar_no_brief", 400, "Write who the person is")


def describing(avatar: dict) -> bool:
    return store._job_active(avatar.get("describe_job_id"))


def _check_idle(avatar: dict) -> None:
    if describing(avatar):
        raise AppError("avatar_describe_busy", 409, "The description is being written; wait or stop it")


# ── starting ────────────────────────────────────────────────────────────────

def start_describe(avatar_id: Any, body: Any = None) -> dict:
    """Queue «Describe». ``body``: ``force`` (replace the current text), and optionally
    ``mode`` / ``brief`` saved first (the same as editing them on the card)."""
    body = body if isinstance(body, dict) else {}
    avatar = store.avatar_row(avatar_id)
    _check_idle(avatar)
    changes = {k: body[k] for k in ("mode", "init_mode", "brief") if k in body}
    if changes:
        store.update(avatar["id"], changes)
        avatar = store.avatar_row(avatar["id"])
    force = bool(body.get("force"))
    _check(avatar, force=force)
    model = describe_model()                  # a refusal now, not after the message is posted
    photos = describe_photos(avatar)
    data = {"mode": avatar["init_mode"], "photo_ids": [p["id"] for p in photos],
            "file_ids": [p["file_id"] for p in photos], "brief": avatar.get("brief") or "",
            "model_id": model["id"], "identity": None, "applied": False}
    message_id = messages.post(avatar, KIND_IDENTITY, text=avatar["name"], status="running", data=data)
    try:
        job_id = jobs.enqueue(JOB_DESCRIBE, {"avatar_id": avatar["id"], "message_id": message_id, "force": force},
                              ref_type=REF_AVATAR, ref_id=avatar["id"], title=f"{avatar['name']} · identity")
    except Exception as exc:
        messages.update(message_id, status="error", error_code=getattr(exc, "code", None) or "internal",
                        error=getattr(exc, "message", None) or str(exc))
        raise
    store.touch(avatar["id"], {"describe_job_id": job_id, "describe_message_id": message_id})
    store.announce(avatar["id"])
    return {"job_id": job_id, "message_id": message_id, "avatar": store.get(avatar["id"])}


# ── the job ─────────────────────────────────────────────────────────────────

def _message_data(message_id: int | None) -> dict:
    if not message_id:
        return {}
    msg = db.get("chat_messages", int(message_id))
    return dict((msg or {}).get("data_json") or {}) if msg else {}


def _close(avatar_id: int, message_id: int | None, status: str, code: str | None, error: str | None) -> None:
    try:
        cost = journal.cost_of(REF_MESSAGE, message_id) if message_id else 0
        messages.update(message_id, status=status, cost_usd=cost, error_code=code, error=error)
        store.refresh_cost(avatar_id)
        store.announce(avatar_id)
    except AppError:
        log.warning("avatar %s: the description message could not be closed as %s", avatar_id, status)


async def _describe(ctx: jobs.JobContext, avatar_id: int, message_id: int | None) -> dict:
    from vf.modules.avatars import draw, subject

    avatar = store.avatar_row(avatar_id)
    _check(avatar, force=True)                # locked or no photos since the start: no money spent
    rows = describe_photos(avatar)
    blobs = await asyncio.to_thread(_blobs, rows)
    if rows and not blobs:
        raise AppError("avatar_photos_unreadable", 400, "The photos could not be read")
    ctx.progress(0.2, force=True)
    ctx.raise_if_cancelled()
    result = await prompts.run_prompt(
        PROMPT_IDENTITY, {"input": input_text(avatar, len(blobs))}, purpose=PURPOSE_IDENTITY, images=blobs,
        temperature=DESCRIBE_TEMPERATURE, max_output_tokens=DESCRIBE_MAX_TOKENS,
        refs=draw.refs_for(avatar, None, message_id), cancel=lambda: ctx.cancel_requested,
    )
    ctx.raise_if_cancelled()
    identity = clean_identity(result.json if isinstance(result.json, dict) else result.text)
    if len(identity) < MIN_IDENTITY:
        raise AppError("avatar_identity_empty", 502, "The model returned too short a description",
                       length=len(identity), min=MIN_IDENTITY, call_ids=result.call_ids)

    current = store.avatar_row(avatar_id)
    applied = not current.get("identity_locked")
    if applied:
        store.touch(avatar_id, {"identity": identity, "identity_source": "model"})
        subject.sync(avatar_id)
    data = {**_message_data(message_id), "identity": identity, "applied": applied, "model_id": result.model_id,
            "photos_used": len(blobs)}
    cost = journal.cost_of(REF_MESSAGE, message_id) if message_id else round(result.cost_usd, 6)
    messages.update(message_id, data=data, status="done" if applied else "error", cost_usd=cost,
                    error_code=None if applied else "avatar_identity_locked", error=None)
    store.refresh_cost(avatar_id)
    store.announce(avatar_id)
    current = store.avatar_row(avatar_id)
    return {"avatar_id": avatar_id, "length": len(identity), "applied": applied, "chat_id": current.get("chat_id"),
            "message_id": message_id, "cost_usd": round(result.cost_usd, 6)}


@jobs.handler(JOB_DESCRIBE, group="text", recover="interrupt")
async def run_describe(ctx: jobs.JobContext) -> dict | None:
    avatar_id = int(ctx.payload.get("avatar_id") or 0)
    message_id = ctx.payload.get("message_id")
    if db.get("avatars", avatar_id) is None:
        return {"skipped": "avatar_gone"}
    try:
        return await _describe(ctx, avatar_id, message_id)
    except GoogleCallError as exc:
        if exc.code == "cancelled" and ctx.cancel_requested:
            _close(avatar_id, message_id, "cancelled", "cancelled", None)
            raise jobs.JobCancelled() from exc
        _close(avatar_id, message_id, "error", exc.code, exc.raw or exc.message)
        raise
    except (asyncio.CancelledError, jobs.JobCancelled):
        if ctx.cancel_requested:   # a stop of the app leaves the message to ``settle`` at the next start
            _close(avatar_id, message_id, "cancelled", "cancelled", None)
        raise
    except AppError as exc:
        _close(avatar_id, message_id, "error", exc.code, exc.message)
        raise
    except Exception as exc:
        _close(avatar_id, message_id, "error", "internal", str(exc) or exc.__class__.__name__)
        raise


# ── by hand ─────────────────────────────────────────────────────────────────

def edit_identity(avatar_id: Any, body: Any) -> dict:
    """The person's own text (any length up to 6000; empty clears it). Not while locked."""
    from vf.modules.avatars import subject

    if not isinstance(body, dict) or "identity" not in body:
        raise AppError("bad_request", 400, "identity is expected")
    avatar = store.avatar_row(avatar_id)
    if avatar.get("identity_locked"):
        raise AppError("avatar_identity_locked", 409, "The description is locked; unlock it first")
    _check_idle(avatar)
    text = clean_lines(str(body["identity"] or ""))
    if len(text) > MAX_IDENTITY:
        raise AppError("avatar_identity_too_long", 400, "The description is too long", max=MAX_IDENTITY)
    store.touch(avatar["id"], {"identity": text, "identity_source": "manual" if text else ""})
    subject.sync(avatar["id"])
    store.announce(avatar["id"])
    return store.get(avatar["id"])


def lock(avatar_id: Any) -> dict:
    avatar = store.avatar_row(avatar_id)
    if not (avatar.get("identity") or "").strip():
        raise AppError("avatar_no_identity", 409, "Describe the person first")
    store.touch(avatar["id"], {"identity_locked": 1})
    store.announce(avatar["id"])
    return store.get(avatar["id"])


def unlock(avatar_id: Any) -> dict:
    """The browser warns first: the face and the shots were drawn from this text."""
    avatar = store.avatar_row(avatar_id)
    store.touch(avatar["id"], {"identity_locked": 0})
    store.announce(avatar["id"])
    return store.get(avatar["id"])


def cancel_describe(avatar_id: Any) -> dict:
    avatar = store.avatar_row(avatar_id)
    job_id = avatar.get("describe_job_id")
    if job_id:
        try:
            job = jobs.cancel(job_id)
        except AppError:
            job = None
        if job is None or job["status"] in jobs.FINISHED:
            settle(avatar["id"])
    return store.get(avatar["id"])


# ── left behind ─────────────────────────────────────────────────────────────

def settle(avatar_id: int) -> bool:
    """A «Describe» message still running while its job is over (the app stopped): close it."""
    avatar = db.get("avatars", avatar_id)
    if avatar is None or not avatar.get("describe_message_id"):
        return False
    msg = db.get("chat_messages", avatar["describe_message_id"])
    if msg is None or msg["status"] != "running":
        return False
    job = db.get("jobs", avatar["describe_job_id"]) if avatar.get("describe_job_id") else None
    if job is not None and job["status"] in jobs.ACTIVE:
        return False
    if job is not None and job["status"] == "done":
        status, code, error = "done", None, None
    elif job is not None and job["status"] == "cancelled":
        status, code, error = "cancelled", "cancelled", None
    else:
        status = "error"
        code = (job or {}).get("error_code") or ((job or {}).get("status") if job else "interrupted")
        error = (job or {}).get("error")
    _close(avatar_id, avatar["describe_message_id"], status, code, error)
    return True


def settle_all() -> int:
    rows = db.fetch_all("SELECT id FROM avatars WHERE describe_message_id IS NOT NULL")
    return sum(1 for r in rows if settle(r["id"]))


__all__ = ["cancel_describe", "describe_model", "describe_photos", "edit_identity", "input_text", "lock", "price",
           "run_describe", "settle", "settle_all", "start_describe", "unlock"]
