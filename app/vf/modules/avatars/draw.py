"""Drawing avatar pictures: face candidates, the shots of the pack, a fix of a shot.

One job = one Google image request for one picture (``avatar.photo``, jobs group
"avatar": 2 at a time by default). Every request goes through the gateway, so it
lands in the spend journal with the avatar, the picture, the chat and the chat
message as refs.

A slot keeps its old picture while it is redrawn or fixed; the new one replaces
it only when it has arrived. «Finish» sends only slots without a picture, and a
slot that got a picture while waiting in the queue is skipped, so nothing is
paid for twice.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from vf.core import db, files, google, jobs, prompts
from vf.core.errors import AppError
from vf.core.google import GoogleCallError, journal
from vf.modules.avatars import compose, messages, store
from vf.modules.avatars.common import (
    ASPECT,
    BUSY,
    FACE_CODE,
    JOB_PHOTO,
    KIND_CANDIDATES,
    KIND_PACK,
    REF_AVATAR,
    REF_MESSAGE,
    REF_PHOTO,
    SHOT_HEIGHT,
    SHOT_WIDTH,
    SOURCE_IMAGE,
    STUCK_MINUTES,
    log,
)

PACK_MODES = ("pack", "finish", "redraw", "fix")


# ── picture state helpers ───────────────────────────────────────────────────

def _ours(row: dict | None, job_id: int | None) -> bool:
    """The picture still waits for this job (not settled by the sweeper or another request)."""
    if row is None:
        return False
    return job_id is None or (row.get("job_id") == job_id and row["status"] in BUSY)


def _after(row: dict) -> None:
    messages.refresh(row.get("message_id"))
    store.announce(row["avatar_id"], photo_id=row["id"])


def restore(photo_id: int, job_id: int | None = None) -> None:
    """Back to how it was before the request: done with its picture, or empty."""
    row = db.get("avatar_photos", photo_id)
    if not _ours(row, job_id):
        return
    store.set_photo(photo_id, {"status": "done" if row.get("file_id") else "empty", "drawing_since": None})
    _after(row)


def fail(photo_id: int, code: str, text: str | None, job_id: int | None = None) -> None:
    row = db.get("avatar_photos", photo_id)
    if not _ours(row, job_id):
        return
    store.set_photo(photo_id, {"status": "error", "error_code": code, "error_text": (text or "")[:4000] or None,
                               "drawing_since": None})
    _after(row)


def refs_for(avatar: dict, photo_id: int | None, message_id: int | None) -> list[tuple[str, int]]:
    """The journal refs of a paid call: the avatar, the picture, the chat and its message."""
    from vf.modules.chat.usage import REF_CHAT

    refs: list[tuple[str, int]] = [(REF_AVATAR, avatar["id"])]
    if photo_id:
        refs.append((REF_PHOTO, photo_id))
    if avatar.get("chat_id"):
        refs.append((REF_CHAT, avatar["chat_id"]))
    if message_id:
        refs.append((REF_MESSAGE, message_id))
    return refs


# ── the job ─────────────────────────────────────────────────────────────────

def _fit(data: bytes, mime: str, base: bytes | None) -> tuple[bytes, str, str]:
    """The answer at exactly 864×1152 (a 1K 3:4 answer is 896×1200)."""
    from vf.modules.studio import imaging

    try:
        fit = imaging.fit_to_frame(data, SHOT_WIDTH, SHOT_HEIGHT, base)
    except Exception:  # noqa: BLE001
        log.warning("could not fit the avatar picture; kept as it came", exc_info=True)
        return data, mime, "kept as it came"
    if fit.image is None:
        return data, mime, fit.note
    return fit.image, "image/png", fit.note


@jobs.handler(JOB_PHOTO, group="avatar")
async def run_photo(ctx: jobs.JobContext) -> dict | None:
    payload = ctx.payload
    photo_id = int(payload["photo_id"])
    row = db.get("avatar_photos", photo_id)
    if row is None:
        messages.refresh(payload.get("message_id"))
        return {"skipped": "photo_gone"}
    if row.get("job_id") and row["job_id"] != ctx.id and row["status"] in BUSY:
        other = db.get("jobs", row["job_id"])
        if other and other["status"] in jobs.ACTIVE:
            raise AppError("avatar_photo_busy", 409, "The picture is being drawn by another request")
    if payload.get("fill") and row.get("file_id"):
        # «Finish»: the slot got a picture while waiting (an own photo, another request): nothing to pay for.
        restore(photo_id, ctx.id)
        return {"skipped": "has_picture"}
    store.set_photo(photo_id, {"status": "drawing", "drawing_since": db.now(), "job_id": ctx.id,
                               "error_code": None, "error_text": None})
    store.announce(row["avatar_id"], photo_id=photo_id)
    try:
        return await _draw(ctx, photo_id, payload)
    except GoogleCallError as exc:
        if exc.code == "cancelled" and ctx.cancel_requested:
            restore(photo_id, ctx.id)
            raise jobs.JobCancelled() from exc
        fail(photo_id, exc.code, exc.raw or exc.message, ctx.id)
        raise
    except (asyncio.CancelledError, jobs.JobCancelled):
        if ctx.cancel_requested:
            restore(photo_id, ctx.id)
        raise   # app shutdown: the picture is settled when the job is seen interrupted
    except AppError as exc:
        fail(photo_id, exc.code, exc.message, ctx.id)
        raise
    except Exception as exc:
        fail(photo_id, "internal", str(exc) or exc.__class__.__name__, ctx.id)
        raise
    finally:
        try:
            store.refresh_cost(row["avatar_id"])
            messages.refresh(payload.get("message_id"))
        except Exception:  # noqa: BLE001
            log.warning("avatar %s: could not refresh the money", row["avatar_id"], exc_info=True)


async def _draw(ctx: jobs.JobContext, photo_id: int, payload: dict) -> dict:
    row = store.photo_row(photo_id)
    avatar = store.avatar_row(row["avatar_id"])
    mode = str(payload.get("mode") or "shot")
    plan = compose.plan_for(avatar, row, mode, payload.get("fix"))
    base = await asyncio.to_thread(files.read_bytes, row["file_id"]) if mode == "fix" else None
    contents = await asyncio.to_thread(plan.contents)
    ctx.progress(0.1, force=True)
    ctx.raise_if_cancelled()

    rp = prompts.render(plan.prompt_code, prompt=plan.text)
    result = await google.generate(
        purpose=plan.purpose, contents=[*contents, rp.text], model_id=plan.model["id"],
        prompt=google.PromptInfo(rp.code, rp.version), response="image", aspect_ratio=ASPECT,
        image_size=plan.image_size, temperature=1.0,
        refs=refs_for(avatar, photo_id, payload.get("message_id")),
        cancel=lambda: ctx.cancel_requested,
    )
    ctx.raise_if_cancelled()
    data, mime = result.images[0]
    data, mime, note = await asyncio.to_thread(_fit, data, mime, base)
    label = row.get("shot_code") or f"{row['kind']} {(row.get('meta_json') or {}).get('variation') or ''}".strip()
    saved = files.save_bytes(data, mime=mime, name=f"avatar-{avatar['id']}-{photo_id}.png", origin="generated",
                             title=f"{avatar['name']} · {label}", source_type=SOURCE_IMAGE, source_id=photo_id,
                             meta={"avatar_id": avatar["id"], "photo_id": photo_id, "mode": mode,
                                   "model_id": result.model_id, "image_size": plan.image_size, "fit": note})

    with db.tx():
        current = db.get("avatar_photos", photo_id)
        if current is None:   # removed while drawing: the picture stays in the media library
            return {"file_id": saved["id"], "photo_gone": True}
        old = current.get("file_id")
        meta = dict(current.get("meta_json") or {})
        meta.update({"sent": plan.attachments(), "mode": mode, "model_id": result.model_id,
                     "image_size": plan.image_size, "fit": note, "fix": payload.get("fix") if mode == "fix" else None})
        if old and old != saved["id"]:
            meta["previous_file_ids"] = [*(meta.get("previous_file_ids") or []), old][-10:]
        store.set_photo(photo_id, {
            "status": "done", "file_id": saved["id"], "origin": "generated", "drawing_since": None,
            "error_code": None, "error_text": None, "prompt_text": plan.text, "meta_json": meta,
            "cost_usd": journal.cost_of(REF_PHOTO, photo_id),
        })
    if old and old != saved["id"]:
        from vf.modules.avatars import photos

        if current.get("marked"):
            from vf.modules.avatars import subject

            subject.sync(avatar["id"])
        photos.drop_file(old)   # only an uploaded own photo is deleted; drawn pictures stay in the library
    store.announce(avatar["id"], photo_id=photo_id)
    # chat_id / message_id: the jobs list leads to the message the picture belongs to
    return {"file_id": saved["id"], "cost_usd": round(result.cost_usd, 6), "avatar_id": avatar["id"],
            "chat_id": avatar.get("chat_id"), "message_id": payload.get("message_id")}


# ── starting ────────────────────────────────────────────────────────────────

def _job_title(avatar: dict, row: dict) -> str:
    if row["kind"] == "candidate":
        return f"{avatar['name']} · #{(row.get('meta_json') or {}).get('variation') or row['id']}"
    return f"{avatar['name']} · {row.get('shot_code') or row['id']}"


def _enqueue(avatar: dict, row: dict, payload: dict, message_id: int | None) -> int:
    """Queue a request for a picture (inside ``db.tx``; the picture must not be busy)."""
    job_id = jobs.enqueue(JOB_PHOTO, {**payload, "photo_id": row["id"], "message_id": message_id},
                          ref_type=REF_PHOTO, ref_id=row["id"], title=_job_title(avatar, row))
    store.set_photo(row["id"], {"status": "queued", "job_id": job_id, "error_code": None, "error_text": None,
                                "message_id": message_id})
    return job_id


def _check_free(row: dict) -> None:
    if row["status"] in BUSY:
        raise AppError("avatar_photo_busy", 409, "The picture is being drawn; wait or stop it")


def _close_failed(message_id: int | None, exc: Exception) -> None:
    messages.update(message_id, status="error", error_code=getattr(exc, "code", None) or "internal",
                    error=getattr(exc, "message", None) or str(exc))


def start_candidates(avatar_id: Any, body: Any = None) -> dict:
    """Draw face candidates (the number and the model are the avatar's saved choices;
    ``body`` may change them first). Each candidate is a separate paid request."""
    from vf.modules.avatars.common import MAX_CANDIDATES

    body = body if isinstance(body, dict) else {}
    choice = {k: body[k] for k in ("candidate_count", "image_model_id") if k in body}
    if "count" in body:
        choice["candidate_count"] = body["count"]
    if choice:
        store.update(avatar_id, choice)
    avatar = store.avatar_row(avatar_id)
    count = min(max(int(avatar["candidate_count"] or 4), 1), MAX_CANDIDATES)
    plan = compose.plan_candidate(avatar, 1)       # every check before money is spent
    message_id = messages.post(avatar, KIND_CANDIDATES, text=avatar["name"], status="running",
                               data={"mode": "candidates", "count": count, "model_id": plan.model["id"],
                                     "photo_ids": []})
    ids: list[int] = []
    try:
        with db.tx():
            first = int(db.fetch_value("SELECT COALESCE(MAX(sort), 0) FROM avatar_photos WHERE avatar_id = ? "
                                       "AND kind = 'candidate'", (avatar["id"],), default=0))
            now = db.now()
            for index in range(1, count + 1):
                photo_id = db.insert("avatar_photos", {
                    "avatar_id": avatar["id"], "kind": "candidate", "sort": first + index, "status": "empty",
                    "origin": "generated", "message_id": message_id,
                    "meta_json": {"variation": index, "model_id": plan.model["id"]},
                    "created_at": now, "updated_at": now,
                })
                _enqueue(avatar, store.photo_row(photo_id), {"mode": "candidate"}, message_id)
                ids.append(photo_id)
    except Exception as exc:
        _close_failed(message_id, exc)
        raise
    messages.update(message_id, data={"avatar_id": avatar["id"], "mode": "candidates", "count": count,
                                      "model_id": plan.model["id"], "photo_ids": ids})
    store.touch(avatar["id"])
    store.announce(avatar["id"])
    return {"queued": ids, "message_id": message_id, "avatar": store.get(avatar["id"])}


def _start_shots(avatar: dict, rows: list[dict], mode: str, *, fix: str | None = None,
                 skipped: list[dict] | None = None) -> dict:
    """Queue shots under one chat message (the result comes back to the chat)."""
    skipped = list(skipped or [])
    ready: list[tuple[dict, dict]] = []
    first_error: AppError | None = None
    for row in rows:
        try:
            if row["status"] in BUSY:
                raise AppError("avatar_photo_busy", 409, "The picture is being drawn; wait or stop it")
            compose.plan_for(avatar, row, "fix" if mode == "fix" else "shot", fix)   # checks before money
        except AppError as exc:
            skipped.append({"photo_id": row["id"], "shot_code": row.get("shot_code"), "reason": exc.code})
            first_error = first_error or exc
            continue
        payload: dict[str, Any] = {"mode": "fix" if mode == "fix" else "shot"}
        if mode == "fix":
            payload["fix"] = fix
        elif not row.get("file_id"):
            payload["fill"] = True      # only a slot that is still empty when its turn comes is drawn
        ready.append((row, payload))
    if not ready:
        if first_error is not None:
            raise first_error
        raise AppError("avatar_nothing_to_draw", 409, "Every shot already has a picture")
    ids = [r["id"] for r, _ in ready]
    data = {"mode": mode, "photo_ids": ids, "codes": [r.get("shot_code") for r, _ in ready],
            "model_id": compose.image_model(avatar)["id"]}
    if fix:
        data["fix"] = fix
    if skipped:
        data["skipped"] = skipped
    message_id = messages.post(avatar, KIND_PACK, text=fix or avatar["name"], status="running", data=data)
    try:
        with db.tx():
            for row, payload in ready:
                current = store.photo_row(row["id"])
                _check_free(current)
                _enqueue(avatar, current, payload, message_id)
    except Exception as exc:
        _close_failed(message_id, exc)
        raise
    store.touch(avatar["id"])
    store.announce(avatar["id"])
    return {"queued": ids, "skipped": skipped, "message_id": message_id, "avatar": store.get(avatar["id"])}


def _codes(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
        raise AppError("bad_request", 400, "codes must be a list of shot codes")
    return value


def start_pack(avatar_id: Any, codes: Any = None, *, mode: str = "pack") -> dict:
    """The ticked shots (``codes``); without codes — every shot that has no picture yet.
    A ticked shot that has a picture is drawn again (the old one stays until the new one comes)."""
    avatar = store.avatar_row(avatar_id)
    codes = _codes(codes)
    slots = [s for s in store.slots_of(avatar["id"]) if s.get("shot_code") != FACE_CODE]
    skipped: list[dict] = []
    if codes is None:
        rows = [s for s in slots if not s.get("file_id") and s["status"] not in BUSY]
    else:
        from vf.modules.avatars import catalog

        for code in codes:
            catalog.shot(code)          # unknown codes are an error, not silently dropped
        wanted = set(codes)
        rows = []
        for s in slots:
            if s["shot_code"] not in wanted:
                continue
            if s["status"] in BUSY:
                skipped.append({"photo_id": s["id"], "shot_code": s["shot_code"], "reason": "avatar_photo_busy"})
            else:
                rows.append(s)
        if FACE_CODE in wanted:
            skipped.append({"photo_id": None, "shot_code": FACE_CODE, "reason": "avatar_face_slot"})
    return _start_shots(avatar, rows, mode, skipped=skipped)


def finish(avatar_id: Any) -> dict:
    """«Finish N unfinished»: only the slots without a picture."""
    return start_pack(avatar_id, None, mode="finish")


def redraw(photo_id: Any) -> dict:
    row = store.photo_row(photo_id)
    if row["kind"] != "shot":
        raise AppError("bad_request", 400, "Only a shot of the pack is drawn again")
    _check_free(row)
    return _start_shots(store.avatar_row(row["avatar_id"]), [row], "redraw")


def fix(photo_id: Any, text: Any) -> dict:
    """«Fix»: one phrase applied over the current picture of the shot."""
    row = store.photo_row(photo_id)
    _check_free(row)
    phrase = compose.clean_fix(text)
    return _start_shots(store.avatar_row(row["avatar_id"]), [row], "fix", fix=phrase)


# ── stopping ────────────────────────────────────────────────────────────────

def cancel(photo_id: Any) -> dict:
    """Stop a queued or running request. A queued one is dropped at once (nothing was paid)."""
    row = store.photo_row(photo_id)
    if row["status"] in BUSY and row.get("job_id"):
        try:
            job = jobs.cancel(row["job_id"])
        except AppError:
            job = None
        if job is None or job["status"] in jobs.FINISHED:
            restore(row["id"])
    elif row["status"] in BUSY:
        restore(row["id"])
    return store.photo_public(store.photo_row(row["id"]))


def cancel_avatar(avatar_id: Any) -> dict:
    """Stop every picture of the avatar that is queued or being drawn."""
    avatar = store.avatar_row(avatar_id)
    for row in db.fetch_all("SELECT id FROM avatar_photos WHERE avatar_id = ? AND status IN ('queued', 'drawing')",
                            (avatar["id"],)):
        cancel(row["id"])
    return store.get(avatar["id"])


# ── pictures left behind ────────────────────────────────────────────────────

def settle(row: dict) -> bool:
    """A picture marked queued/drawing whose job is over or gone: put it in order."""
    if row["status"] not in BUSY:
        return False
    job = db.get("jobs", row["job_id"]) if row.get("job_id") else None
    if job is not None and job["status"] in jobs.ACTIVE:
        return False
    if job is None or job["status"] in ("done", "cancelled"):
        restore(row["id"])
    else:
        fail(row["id"], job.get("error_code") or job["status"], job.get("error"))
    return True


def settle_avatar(avatar_id: int) -> None:
    for row in db.fetch_all("SELECT * FROM avatar_photos WHERE avatar_id = ? AND status IN ('queued', 'drawing')",
                            (avatar_id,)):
        settle(row)


def sweep() -> int:
    """Every minute and at start: settle pictures left behind, and give up on pictures
    drawing for more than 15 minutes (their job is stopped; the slot shows "stuck")."""
    changed = 0
    limit = (datetime.now(UTC) - timedelta(minutes=STUCK_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for row in db.fetch_all("SELECT * FROM avatar_photos WHERE status IN ('queued', 'drawing')"):
        if settle(row):
            changed += 1
        elif row["status"] == "drawing" and row.get("drawing_since") and row["drawing_since"] < limit:
            if row.get("job_id"):
                try:
                    jobs.cancel(row["job_id"])
                except AppError:
                    pass
            fail(row["id"], "stuck", None)
            changed += 1
    return changed


__all__ = ["PACK_MODES", "cancel", "cancel_avatar", "finish", "fix", "redraw", "refs_for", "restore",
           "run_photo", "settle", "settle_avatar", "start_candidates", "start_pack", "sweep"]
