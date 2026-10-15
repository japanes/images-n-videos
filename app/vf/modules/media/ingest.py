"""Video and audio "intake" through the ``render`` service.

For a video: duration and upright size (``probe``), a JPEG poster and a short
WebP hover loop (``preview``) saved next to the file as
``<name>.poster.jpg`` / ``<name>.preview.webp``. For audio: the duration only.
A "video" without a picture (an .mp4 with sound only) becomes audio.

Other modules call ``enqueue_video_ingest(file_id)`` right after they register
a video. A minute sweeper (setting ``media.auto_ingest``) also picks up library
videos that nobody sent here, so every video in the library gets a poster.
The intake state lives in ``files.meta_json["ingest"]``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from vf.core import db, files, jobs, scheduler, settings
from vf.core.errors import AppError
from vf.core.services import render

log = logging.getLogger("vf.media.ingest")

JOB_KIND = "media.ingest"
INGEST_KINDS = ("video", "audio")
SWEEP_GRACE_SECONDS = 30
SWEEP_BATCH = 20
RETRY_AFTER_MINUTES = 5
MAX_ATTEMPTS = 3
RETRYABLE = ("render_unavailable",)
AUDIO_MIME_FOR_VIDEO = {"video/mp4": "audio/mp4", "video/quicktime": "audio/mp4", "video/webm": "audio/webm"}

settings.define("media.auto_ingest", True, group="media", kind="bool")


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def derived_paths(rel: str) -> tuple[str, str]:
    """Where the poster and the hover preview of ``files/…/<uuid>.mp4`` go."""
    p = PurePosixPath(rel)
    stem = str(p.with_suffix(""))
    return f"{stem}.poster.jpg", f"{stem}.preview.webp"


def ingest_state(row: dict) -> dict | None:
    meta = row.get("meta_json")
    if isinstance(meta, dict) and isinstance(meta.get("ingest"), dict):
        return meta["ingest"]
    return None


def _mark(file_id: int, **values: Any) -> dict | None:
    """Merge ``values`` into ``meta_json["ingest"]``; ``None`` when the file is gone."""
    with db.tx():
        row = db.get("files", file_id)
        if row is None:
            return None
        meta = row.get("meta_json") if isinstance(row.get("meta_json"), dict) else {}
        state = dict(meta.get("ingest") or {})
        state.update(values, at=db.now())
        meta = {**meta, "ingest": state}
        db.update("files", file_id, {"meta_json": meta})
    return state


def enqueue_video_ingest(file_id: int, *, priority: int = 0) -> int | None:
    """Queue the intake of a video (or audio) file. Returns the job id, or ``None``
    when the file is not a video/audio. Safe to call twice: jobs of one file run one
    after another."""
    row = files.get(file_id)
    if row["kind"] not in INGEST_KINDS:
        return None
    state = ingest_state(row) or {}
    _mark(file_id, status="queued", error_code=None, error=None, attempts=state.get("attempts") or 0)
    title = row.get("title") or row.get("original_name") or f"{row['kind']} {file_id}"
    return jobs.enqueue(JOB_KIND, {"file_id": file_id}, ref_type="file", ref_id=file_id,
                        title=title, priority=priority)


enqueue_ingest = enqueue_video_ingest


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _drop_thumbs(file_id: int) -> None:
    shutil.rmtree(files.data_dir() / "cache" / "thumbs" / str(file_id), ignore_errors=True)


def _unlink(rel: str | None) -> None:
    if not rel:
        return
    try:
        files.abs_path(rel).unlink(missing_ok=True)
    except (AppError, OSError):
        pass


async def _ingest(ctx: jobs.JobContext, row: dict) -> dict:
    file_id = row["id"]
    ctx.progress(0.05, "probe", force=True)
    meta = await render.probe(row["path"]) or {}
    ctx.raise_if_cancelled()
    values: dict[str, Any] = {}
    duration = _number(meta.get("duration"))
    if duration is not None:
        values["duration"] = round(duration, 3)
    has_video = bool(meta.get("has_video", row["kind"] == "video"))
    if row["kind"] == "video" and not has_video:
        values.update(kind="audio", mime=AUDIO_MIME_FOR_VIDEO.get(row["mime"], "audio/mp4"),
                      width=None, height=None)
    result: dict[str, Any] = {"file_id": file_id, "duration": values.get("duration")}
    if row["kind"] == "video" and has_video:
        width = meta.get("display_width") or meta.get("width")
        height = meta.get("display_height") or meta.get("height")
        if width and height:
            values.update(width=int(width), height=int(height))
        poster_rel, preview_rel = derived_paths(row["path"])
        answer = await render.run("preview", {"input": row["path"], "poster_output": poster_rel,
                                              "preview_output": preview_rel},
                                  ctx=ctx, progress_from=0.15, progress_to=0.95, note="preview")
        poster = (answer.get("poster") or {}).get("output")
        preview = (answer.get("preview") or {}).get("output")
        if db.get("files", file_id) is None:  # deleted while the render worked
            _unlink(poster)
            _unlink(preview)
            return {"file_id": file_id, "skipped": "deleted"}
        values.update(poster_path=poster or None, preview_path=preview or None)
        result.update(poster=bool(poster), preview=bool(preview))
        _drop_thumbs(file_id)
    if db.get("files", file_id) is None:
        return {"file_id": file_id, "skipped": "deleted"}
    if values:
        files.update(file_id, values)
    return result


@jobs.handler(JOB_KIND, group="render", serial_key=lambda p: f"{JOB_KIND}:{p.get('file_id')}", recover="retry")
async def run_ingest(ctx: jobs.JobContext) -> dict:
    file_id = int(ctx.payload["file_id"])
    row = db.get("files", file_id)
    if row is None:
        return {"file_id": file_id, "skipped": "deleted"}
    if row["kind"] not in INGEST_KINDS:
        _mark(file_id, status="done", error_code=None, error=None)
        return {"file_id": file_id, "skipped": row["kind"]}
    attempts = int((ingest_state(row) or {}).get("attempts") or 0) + 1
    _mark(file_id, status="running", attempts=attempts)
    try:
        result = await _ingest(ctx, row)
    except (asyncio.CancelledError, jobs.JobCancelled):
        _mark(file_id, status="cancelled")
        raise
    except AppError as exc:
        _mark(file_id, status="error", error_code=exc.code, error=exc.message[:500])
        raise
    except Exception as exc:
        _mark(file_id, status="error", error_code="internal", error=str(exc)[:500])
        raise
    if not result.get("skipped"):
        _mark(file_id, status="done", error_code=None, error=None)
    return result


def _due(state: dict | None, now: datetime) -> bool:
    if not state:
        return True
    if state.get("status") != "error" or state.get("error_code") not in RETRYABLE:
        return False
    if int(state.get("attempts") or 0) >= MAX_ATTEMPTS:
        return False
    return str(state.get("at") or "") < _stamp(now - timedelta(minutes=RETRY_AFTER_MINUTES))


def sweep(now: datetime | None = None) -> list[int]:
    """Queue the intake for library videos and audio that never had it. Returns the job ids."""
    if not settings.get("media.auto_ingest"):
        return []
    now = now or datetime.now(UTC)
    rows = db.fetch_all(
        "SELECT id, kind, meta_json FROM files WHERE is_service = 0 AND kind IN ('video', 'audio') "
        "AND ((kind = 'video' AND poster_path IS NULL) OR (kind = 'audio' AND duration IS NULL)) "
        "AND created_at < ? ORDER BY id DESC LIMIT 200",
        (_stamp(now - timedelta(seconds=SWEEP_GRACE_SECONDS)),))
    queued: list[int] = []
    for row in rows:
        if len(queued) >= SWEEP_BATCH:
            break
        if not _due(ingest_state(row), now):
            continue
        busy = db.fetch_value("SELECT COUNT(*) FROM jobs WHERE kind = ? AND ref_type = 'file' AND ref_id = ? "
                              "AND status IN ('queued', 'running')", (JOB_KIND, row["id"]), 0)
        if busy:
            continue
        job_id = enqueue_video_ingest(row["id"], priority=-1)
        if job_id:
            queued.append(job_id)
    if queued:
        log.info("queued intake for %d file(s)", len(queued))
    return queued


@scheduler.every_minute
def _sweep_minutely() -> None:
    sweep()
