"""Subtitles from speech: a background job that asks the local ``stt`` service
(faster-whisper, free, runs on this computer) for the words of a video with
their start and end times.

No Google call happens here, so nothing is written to the spend journal.

The first run downloads the model (``large-v3-turbo`` ~1.6 GB or ``small``
~0.5 GB); the editor warns about the size before that. How long recognition
takes is learned from the runs on this computer (seconds of work per minute
of sound); until there are runs, the ``stt.seconds_per_minute_*`` settings
give the guess.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import statistics
from typing import Any

from vf.core import db, events, files, jobs, settings
from vf.core.errors import AppError, NotFound
from vf.core.services import stt
from vf.modules.clip.state import normalize, normalize_words

log = logging.getLogger("vf.clip.transcribe")

JOB_KIND = "clip.transcribe"
MODELS = ("large-v3-turbo", "small")
LANGUAGES = ("auto", "ru", "uk", "en")
POLL_SECONDS = 1.0
SPEED_SAMPLES = 5        # how many recent runs make the time estimate
MIN_SAMPLE_S = 5.0       # shorter recordings say little about speed

SPEED_KEYS = {"large-v3-turbo": "stt.seconds_per_minute_turbo", "small": "stt.seconds_per_minute_small"}

settings.define("stt.model", "large-v3-turbo", group="stt", kind="enum", choices=list(MODELS),
                label_key="clip.settings.model.label", help_key="clip.settings.model.help")
settings.define("stt.language", "auto", group="stt", kind="enum", choices=list(LANGUAGES),
                label_key="clip.settings.language.label", help_key="clip.settings.language.help")
settings.define(SPEED_KEYS["large-v3-turbo"], 40, group="stt", kind="int", min=1, max=3600,
                label_key="clip.settings.speedTurbo.label", help_key="clip.settings.speedTurbo.help")
settings.define(SPEED_KEYS["small"], 15, group="stt", kind="int", min=1, max=3600,
                label_key="clip.settings.speedSmall.label", help_key="clip.settings.speedSmall.help")

# stt progress phases -> share of the job bar
_PHASES = {"starting": (0.0, 0.0), "downloading": (0.0, 0.5), "decoding": (0.5, 0.6),
           "loading": (0.6, 0.6), "transcribing": (0.6, 1.0)}


def check_model(name: str | None) -> str:
    model = name or settings.get("stt.model") or MODELS[0]
    if model not in MODELS:
        raise AppError("clip_stt_model", 400, "Unknown speech recognition model", model=model, allowed=list(MODELS))
    return model


def check_language(code: str | None) -> str:
    lang = code or settings.get("stt.language") or "auto"
    if lang not in LANGUAGES:
        raise AppError("clip_stt_language", 400, "Unknown language", language=lang, allowed=list(LANGUAGES))
    return lang


# ── estimate ────────────────────────────────────────────────────────────────

def speed(model: str) -> dict:
    """Seconds of work per minute of sound: the median of the recent runs, else the setting."""
    rows = db.fetch_all(
        "SELECT duration, elapsed_s FROM transcripts WHERE model = ? AND elapsed_s > 0 AND duration >= ? "
        "ORDER BY id DESC LIMIT ?", (model, MIN_SAMPLE_S, SPEED_SAMPLES))
    samples = [r["elapsed_s"] / (r["duration"] / 60.0) for r in rows if r["duration"]]
    if samples:
        return {"seconds_per_minute": round(statistics.median(samples), 1), "measured": True, "samples": len(samples)}
    value = settings.get(SPEED_KEYS.get(model, ""), 30) or 30
    return {"seconds_per_minute": float(value), "measured": False, "samples": 0}


def estimate(model: str, duration: float | None) -> dict:
    out: dict[str, Any] = {"model": model, **speed(model)}
    out["duration"] = duration
    out["expected_s"] = round(out["seconds_per_minute"] * float(duration) / 60.0) if duration else None
    return out


# ── transcripts ─────────────────────────────────────────────────────────────

def transcript_dict(row: dict, *, words: bool = True) -> dict:
    out = {
        "id": row["id"], "file_id": row["file_id"], "model": row["model"],
        "requested_language": row["requested_language"], "language": row["language"],
        "text": row["text"], "duration": row["duration"], "elapsed_s": row["elapsed_s"],
        "created_at": row["created_at"],
    }
    if words:
        out["words"] = row.get("words_json") or []
    return out


def get_transcript(transcript_id: int) -> dict:
    row = db.get("transcripts", transcript_id)
    if row is None:
        raise NotFound("transcript", id=transcript_id)
    return transcript_dict(row)


def find_transcript(file_id: int, model: str, language: str) -> dict | None:
    return db.fetch_one(
        "SELECT * FROM transcripts WHERE file_id = ? AND model = ? AND requested_language = ? ORDER BY id DESC LIMIT 1",
        (file_id, model, language))


def _apply_to_project(project_id: int, row: dict, *, replace: bool) -> bool:
    """Put the words into the project's subtitles when they are empty (or when asked)."""
    project = db.get("clip_projects", project_id)
    if project is None:
        return False
    state = normalize(project.get("state_json") or {}, (project.get("source_json") or {}).get("duration"))
    sub = state["subtitles"]
    if sub["words"] and not replace:
        return False
    sub["words"] = normalize_words(row.get("words_json") or [])
    sub["transcript_id"] = row["id"]
    sub["language"] = row.get("language")
    sub["enabled"] = True
    db.update("clip_projects", project_id, {"state_json": state, "updated_at": db.now()})
    return True


def start(project_id: int, *, model: str | None = None, language: str | None = None, force: bool = False,
          replace: bool = False) -> dict:
    """Reuse a saved transcript of the same file, model and language, or queue the job."""
    project = db.get("clip_projects", project_id)
    if project is None:
        raise NotFound("clip project", id=project_id)
    model = check_model(model)
    language = check_language(language)
    if not force:
        row = find_transcript(project["file_id"], model, language)
        if row is not None:
            applied = _apply_to_project(project_id, row, replace=replace)
            events.publish("clip.updated", {"project_id": project_id, "what": "transcript", "transcript_id": row["id"]})
            return {"transcript": transcript_dict(row), "applied": applied, "job_id": None}
    for job in jobs.list_jobs(active_only=True, ref_type="clip", ref_id=project_id, limit=20):
        if job["kind"] == JOB_KIND:
            return {"transcript": None, "applied": False, "job_id": job["id"]}
    job_id = jobs.enqueue(JOB_KIND, {"project_id": project_id, "model": model, "language": language,
                                     "replace": bool(replace)},
                          ref_type="clip", ref_id=project_id, title=project["title"])
    return {"transcript": None, "applied": False, "job_id": job_id}


# ── job ─────────────────────────────────────────────────────────────────────

def _bar(state: dict) -> tuple[float | None, str | None]:
    phase = state.get("phase")
    span = _PHASES.get(phase)
    if span is None:
        return None, None
    lo, hi = span
    value = state.get("progress")
    try:
        part = min(1.0, max(0.0, float(value))) if value is not None else 0.0
    except (TypeError, ValueError):
        part = 0.0
    return lo + (hi - lo) * part, phase


def _error(exc: AppError) -> AppError:
    """stt errors -> codes the editor can explain (``stt_busy``, ``stt_no_audio`` ...)."""
    if exc.code == "stt_failed":
        code = exc.details.get("service_code")
        if code:
            return AppError(f"stt_{code}", exc.status, exc.message, **exc.details)
    return exc


@jobs.handler(JOB_KIND, group="stt", recover="interrupt")
async def run_transcribe(ctx: jobs.JobContext) -> dict:
    project_id = int(ctx.payload["project_id"])
    model = check_model(ctx.payload.get("model"))
    language = check_language(ctx.payload.get("language"))
    project = db.get("clip_projects", project_id)
    if project is None:
        return {"project_id": project_id, "skipped": "deleted"}
    source = files.get(project["file_id"])
    ctx.progress(0.0, "starting", force=True)

    loop = asyncio.get_running_loop()
    began = loop.time()
    task = asyncio.create_task(stt.transcribe(source["path"], model=model, language=language))
    work_started: float | None = None
    downloading = False
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=POLL_SECONDS)
            if done:
                break
            if ctx.cancelled:
                task.cancel()
                ctx.raise_if_cancelled()
            with contextlib.suppress(AppError):
                state = await stt.progress()
                if state.get("phase") == "downloading":
                    downloading = True
                elif state.get("busy") and state.get("phase") not in (None, "starting"):
                    work_started = work_started or loop.time()
                value, phase = _bar(state)
                if value is not None:
                    ctx.progress(value, phase)
        result = task.result()
    except AppError as exc:
        raise _error(exc) from exc
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
    # Time of the recognition itself; a model download in the same run does not count.
    if work_started is None and not downloading:
        work_started = began
    elapsed = round(loop.time() - work_started, 2) if work_started is not None else None
    ctx.raise_if_cancelled()

    words = normalize_words(result.get("words") or [])
    duration = result.get("duration") or source.get("duration")
    transcript_id = db.insert("transcripts", {
        "file_id": source["id"], "engine": "faster-whisper", "model": result.get("model") or model,
        "requested_language": language, "language": result.get("language"),
        "text": str(result.get("text") or "").strip(), "words_json": words,
        "duration": float(duration) if duration else None, "elapsed_s": elapsed,
        "job_id": ctx.id, "created_at": db.now(),
    })
    row = db.get("transcripts", transcript_id) or {}
    applied = _apply_to_project(project_id, row, replace=bool(ctx.payload.get("replace")))
    ctx.progress(1.0, "done", force=True)
    events.publish("clip.updated", {"project_id": project_id, "what": "transcript", "transcript_id": transcript_id})
    return {"project_id": project_id, "transcript_id": transcript_id, "words": len(words), "applied": applied}


# ── models ──────────────────────────────────────────────────────────────────

async def models() -> dict:
    """Models of the stt service plus what this app knows about them."""
    items = await stt.models()
    try:
        state = await stt.progress()
    except AppError:
        state = {}
    return {"items": items, "progress": state, "default": check_model(None), "language": check_language(None)}


async def download(name: str) -> dict:
    check_model(name)
    try:
        return await stt.download(name) or {}
    except AppError as exc:
        raise _error(exc) from exc


async def remove(name: str) -> None:
    check_model(name)
    try:
        await stt.remove(name)
    except AppError as exc:
        raise _error(exc) from exc
