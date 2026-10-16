"""Drawing frames: the background job, starting it, stopping it, putting a frame
back in order when its job ended without it (restart, crash, cancel).

One job = one Google image request for one frame (a full generation or a
correction). Every request goes through the gateway, so it lands in the spend
journal with the work and the frame as refs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from vf.core import db, files, google, jobs, prompts
from vf.core.errors import AppError
from vf.core.google import GoogleCallError, journal
from vf.modules.studio import compose, imaging
from vf.modules.studio import works as W
from vf.modules.studio.common import (
    BUSY,
    MAX_VERSIONS,
    PURPOSE_EDIT,
    PURPOSE_FRAME,
    SOURCE_FRAME,
    STUCK_MINUTES,
    publish,
)

log = logging.getLogger("vf.studio")

JOB_KIND = "studio.frame"


# ── frame state helpers ─────────────────────────────────────────────────────

def _set(frame_id: int, values: dict) -> None:
    values["updated_at"] = db.now()
    db.update("frames", frame_id, values)


def _announce(frame_id: int) -> None:
    row = db.get("frames", frame_id)
    if row:
        publish("frame", work_id=row["work_id"], frame_id=frame_id, status=row["status"])


def _ours(row: dict | None, job_id: int | None) -> bool:
    """The frame still waits for this job (not settled by the sweeper or another request)."""
    if row is None:
        return False
    return job_id is None or (row.get("job_id") == job_id and row["status"] in BUSY)


def restore(frame_id: int, job_id: int | None = None) -> None:
    """Back to how it was before the request: done with its picture, or empty.
    With ``job_id``: only while the frame still waits for that job."""
    row = db.get("frames", frame_id)
    if not _ours(row, job_id):
        return
    _set(frame_id, {"status": "done" if row.get("file_id") else "empty", "drawing_since": None})
    _announce(frame_id)


def fail(frame_id: int, code: str, text: str | None, job_id: int | None = None) -> None:
    if not _ours(db.get("frames", frame_id), job_id):
        return
    _set(frame_id, {"status": "error", "error_code": code, "error_text": (text or "")[:4000] or None,
                    "drawing_since": None})
    _announce(frame_id)


def push_version(frame: dict, version: dict) -> list[dict]:
    """Add a version; keep the last ``MAX_VERSIONS`` (the pictures stay in the media library)."""
    versions = list(frame.get("versions_json") or [])
    versions.append(version)
    return versions[-MAX_VERSIONS:]


def _work_active(work_id: int) -> None:
    db.execute("UPDATE image_works SET status = 'active', updated_at = ? WHERE id = ? AND status = 'draft'",
               (db.now(), work_id))


# ── the job ─────────────────────────────────────────────────────────────────

def _fit(plan: compose.Plan, work: dict, data: bytes, mime: str, base: bytes | None) -> tuple[bytes, str, str]:
    """The answer at the frame's exact size: the configured size for 1K pictures;
    otherwise the model's own size with the asked proportions made exact."""
    try:
        if plan.target:
            width, height = plan.target
        else:
            width, height = imaging.aspect_target(*imaging.image_size(data), work["aspect"])
        fit = imaging.fit_to_frame(data, width, height, base)
    except Exception:  # noqa: BLE001
        log.warning("could not fit the answer to the frame; kept as it came", exc_info=True)
        return data, mime, "kept as it came"
    if fit.image is None:
        return data, mime, fit.note
    return fit.image, "image/png", fit.note


@jobs.handler(JOB_KIND, group="image")
async def run_frame(ctx: jobs.JobContext) -> dict | None:
    payload = ctx.payload
    frame_id = int(payload["frame_id"])
    frame = db.get("frames", frame_id)
    if frame is None:
        return {"skipped": "frame_gone"}
    if frame.get("job_id") and frame["job_id"] != ctx.id and frame["status"] in BUSY:
        other = db.get("jobs", frame["job_id"])
        if other and other["status"] in jobs.ACTIVE:
            raise AppError("frame_busy", 409, "The frame is being drawn by another request")
    mode = "edit" if payload.get("mode") == "edit" else "full"
    _set(frame_id, {"status": "drawing", "drawing_since": db.now(), "job_id": ctx.id, "error_code": None,
                    "error_text": None})
    _announce(frame_id)
    try:
        return await _draw(ctx, frame_id, mode, payload)
    except GoogleCallError as exc:
        if exc.code == "cancelled" and ctx.cancel_requested:
            restore(frame_id, ctx.id)
            raise jobs.JobCancelled() from exc
        fail(frame_id, exc.code, exc.raw or exc.message, ctx.id)
        raise
    except (asyncio.CancelledError, jobs.JobCancelled):
        if ctx.cancel_requested:
            restore(frame_id, ctx.id)
        raise   # app shutdown: the frame is settled when the job is seen interrupted
    except AppError as exc:
        fail(frame_id, exc.code, exc.message, ctx.id)
        raise
    except Exception as exc:
        fail(frame_id, "internal", str(exc) or exc.__class__.__name__, ctx.id)
        raise


async def _draw(ctx: jobs.JobContext, frame_id: int, mode: str, payload: dict) -> dict:
    frame = W.frame_row(frame_id)
    work = W.work_row(frame["work_id"])
    eff = W.effective(work, frame)
    base = None
    if mode == "edit":
        if not frame.get("file_id"):
            raise AppError("frame_no_picture", 409, "The frame has no picture to correct")
        base = files.read_bytes(frame["file_id"])
        region = payload.get("region")
        plan = compose.plan_edit(work, frame, payload.get("edit") or "", region, eff, base_bytes=base)
    else:
        plan = compose.plan_full(work, frame, eff)
    contents = await asyncio.to_thread(plan.contents)
    _set(frame_id, {"prompt_text": plan.text, "attachments_json": plan.attachments()})
    ctx.progress(0.1, force=True)
    ctx.raise_if_cancelled()

    rp = prompts.render("STUDIO_FRAME", prompt=plan.text)
    result = await google.generate(
        purpose=PURPOSE_EDIT if mode == "edit" else PURPOSE_FRAME,
        contents=[*contents, rp.text], model_id=eff["model_id"],
        prompt=google.PromptInfo(rp.code, rp.version), response="image", aspect_ratio=work["aspect"],
        image_size=eff["image_size"], temperature=1.0,
        refs=[(W.REF_WORK, work["id"]), (W.REF_FRAME, frame_id)],
        cancel=lambda: ctx.cancel_requested,
    )
    ctx.raise_if_cancelled()
    data, mime = result.images[0]
    data, mime, note = await asyncio.to_thread(_fit, plan, work, data, mime, base)
    title = f"{work['title'] or 'Image studio'} · {frame['position'] + 1}"
    saved = files.save_bytes(data, mime=mime, name=f"frame-{frame_id}.png", origin="generated", title=title,
                             source_type=SOURCE_FRAME, source_id=frame_id,
                             meta={"work_id": work["id"], "frame_id": frame_id, "mode": mode,
                                   "model_id": result.model_id, "fit": note})

    with db.tx():
        current = db.get("frames", frame_id)
        if current is None:   # deleted while drawing: the picture stays in the media library
            return {"file_id": saved["id"], "frame_gone": True}
        version = {
            "file_id": saved["id"], "at": db.now(), "mode": mode, "prompt_text": plan.text,
            "source": "generated" if mode == "full" else current["source"],
            "cost_usd": round(result.cost_usd, 6), "call_ids": result.call_ids, "model_id": result.model_id,
            "image_size": eff["image_size"],
        }
        values: dict[str, Any] = {
            "status": "done", "file_id": saved["id"], "clean_file_id": saved["id"], "drawing_since": None,
            "versions_json": push_version(current, version), "error_code": None, "error_text": None,
            "cost_usd": journal.cost_of(W.REF_FRAME, frame_id),
        }
        if mode == "full":
            values["source"] = "generated"
            values["source_ref_json"] = None
        _set(frame_id, values)
        _work_active(work["id"])
    _announce(frame_id)
    return {"file_id": saved["id"], "cost_usd": round(result.cost_usd, 6)}


# ── starting and stopping ───────────────────────────────────────────────────

def _job_title(work: dict, frame: dict) -> str:
    return f"{work['title'] or '#' + str(work['id'])} · {frame['position'] + 1}"


def _enqueue(work: dict, frame: dict, payload: dict) -> int:
    """Queue a request for a frame (inside ``db.tx``; the frame must not be busy)."""
    job_id = jobs.enqueue(JOB_KIND, payload, ref_type=W.REF_FRAME, ref_id=frame["id"],
                          title=_job_title(work, frame))
    _set(frame["id"], {"status": "queued", "job_id": job_id, "error_code": None, "error_text": None})
    return job_id


def _check_free(frame: dict) -> None:
    if frame["status"] in BUSY:
        raise AppError("frame_busy", 409, "The frame is being drawn; wait or stop it")


def start_frame(frame_id: int) -> dict:
    """Draw one frame again from its brief and settings."""
    frame = W.frame_row(frame_id)
    _check_free(frame)
    work = W.work_row(frame["work_id"])
    compose.plan_full(work, frame)              # every check before money is spent
    with db.tx():
        frame = W.frame_row(frame_id)
        _check_free(frame)
        job_id = _enqueue(work, frame, {"frame_id": frame_id, "mode": "full"})
    _announce(frame_id)
    return {"job_id": job_id, "frame": W.frame_public(W.frame_row(frame_id))}


def start_edit(frame_id: int, edit: str, region: Any = None) -> dict:
    """Correct the current picture (optionally one picked object)."""
    frame = W.frame_row(frame_id)
    _check_free(frame)
    if not frame.get("file_id"):
        raise AppError("frame_no_picture", 409, "The frame has no picture to correct")
    work = W.work_row(frame["work_id"])
    picked = compose.find_region(frame, region)
    edit = str(edit or "")
    compose.plan_edit(work, frame, edit, picked)     # every check before money is spent
    with db.tx():
        frame = W.frame_row(frame_id)
        _check_free(frame)
        job_id = _enqueue(work, frame, {"frame_id": frame_id, "mode": "edit", "edit": edit, "region": picked})
    _announce(frame_id)
    return {"job_id": job_id, "frame": W.frame_public(W.frame_row(frame_id))}


def all_targets(work: dict) -> tuple[list[dict], list[dict]]:
    """Which frames "draw all" sends: ``([frame], [{frame_id, reason}])``.

    Frames with a picked picture (not generated) and busy frames are skipped; a
    series whose pilot is not accepted yet draws only the pilot."""
    s = W.settings_of(work)
    targets, skipped = [], []
    for frame in W.frames_of(work["id"]):
        if frame["source"] != "generated" and frame.get("file_id"):
            skipped.append({"frame_id": frame["id"], "reason": "not_generated"})
        elif frame["status"] in BUSY:
            skipped.append({"frame_id": frame["id"], "reason": "frame_busy"})
        elif s["series"] and not s["pilot_accepted"] and frame["position"] > 0:
            skipped.append({"frame_id": frame["id"], "reason": "pilot_not_ready"})
        else:
            targets.append(frame)
    return targets, skipped


def _start_many(work: dict, frames: list[dict], skipped: list[dict], strict: bool = True) -> dict:
    """Queue the frames; the ones that cannot go are listed in skipped. strict: when none could
    go, the first reason is raised as the error (nothing happened, so the person must see why)."""
    queued, first_error = [], None
    with db.tx():
        for frame in frames:
            try:
                compose.plan_full(work, frame)
            except AppError as exc:
                skipped.append({"frame_id": frame["id"], "reason": exc.code})
                first_error = first_error or exc
                continue
            _enqueue(work, frame, {"frame_id": frame["id"], "mode": "full"})
            queued.append(frame["id"])
    if strict and not queued and first_error is not None:
        raise first_error
    for frame_id in queued:
        _announce(frame_id)
    return {"queued": queued, "skipped": skipped, "work": W.get_work(work["id"])}


def start_all(work_id: int) -> dict:
    """Draw every generated frame of the work (each one is a separate paid request)."""
    work = W.work_row(work_id)
    targets, skipped = all_targets(work)
    return _start_many(work, targets, skipped)


def pilot_targets(work: dict) -> list[dict]:
    """After the pilot is accepted: the other frames still without a picture."""
    return [f for f in W.frames_of(work["id"])[1:]
            if f["source"] == "generated" and f["status"] in ("empty", "error")]


def accept_pilot(work_id: int) -> dict:
    """The pilot's look is approved: the other frames follow it. Draws the empty ones."""
    work = W.work_row(work_id)
    s = W.settings_of(work)
    pilot = W.pilot_frame(work)
    if not s["series"] or pilot is None or pilot["status"] != "done" or not pilot.get("file_id"):
        raise AppError("pilot_not_ready", 409, "The first frame has no picture yet")
    s["pilot_frame_id"], s["pilot_accepted"] = pilot["id"], True
    db.update("image_works", work_id, {"settings_json": s, "updated_at": db.now()})
    work = W.work_row(work_id)
    # The approval is saved even when no other frame can go yet (e.g. no brief): not an error.
    return _start_many(work, pilot_targets(work), [], strict=False)


def cancel_frame(frame_id: int) -> dict:
    """Stop a queued or running request. A queued one is dropped at once (nothing was paid)."""
    frame = W.frame_row(frame_id)
    if frame["status"] in BUSY and frame.get("job_id"):
        try:
            job = jobs.cancel(frame["job_id"])
        except AppError:
            job = None
        if job is None or job["status"] in jobs.FINISHED:
            restore(frame_id)
    elif frame["status"] in BUSY:
        restore(frame_id)
    return W.frame_public(W.frame_row(frame_id))


# ── frames left behind ──────────────────────────────────────────────────────

def settle(frame: dict) -> bool:
    """A frame marked queued/drawing whose job is over or gone: put it in order.
    Returns True when the frame was changed."""
    if frame["status"] not in BUSY:
        return False
    job = db.get("jobs", frame["job_id"]) if frame.get("job_id") else None
    if job is not None and job["status"] in jobs.ACTIVE:
        return False
    if job is None or job["status"] in ("done", "cancelled"):
        restore(frame["id"])
    else:
        fail(frame["id"], job.get("error_code") or job["status"], job.get("error"))
    return True


def settle_work(work_id: int) -> None:
    for frame in db.fetch_all("SELECT * FROM frames WHERE work_id = ? AND status IN ('queued', 'drawing')",
                              (work_id,)):
        settle(frame)


def sweep() -> int:
    """Every minute: settle frames left behind, and give up on frames drawing for too long
    (their job is stopped; the frame shows "stuck")."""
    changed = 0
    limit = (datetime.now(UTC) - timedelta(minutes=STUCK_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for frame in db.fetch_all("SELECT * FROM frames WHERE status IN ('queued', 'drawing')"):
        if settle(frame):
            changed += 1
        elif frame["status"] == "drawing" and frame.get("drawing_since") and frame["drawing_since"] < limit:
            if frame.get("job_id"):
                try:
                    jobs.cancel(frame["job_id"])
                except AppError:
                    pass
            fail(frame["id"], "stuck", None)
            changed += 1
    return changed
