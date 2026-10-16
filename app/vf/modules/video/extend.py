"""Making a finished video longer.

**Extension** (a model that takes a video as input, e.g. Omni): the last L seconds
of the current version (the tail, L = min(video length, setting, model ceiling))
are sent with "what happens next"; the model answers with the tail plus the new
seconds. The head (0..T-L) and the answer are joined on the frame at T-L.

**Continue from the last frame**: the last frame becomes the first frame of a new
take on any video model (Veo too); the new piece is joined to the video.

Several extensions in a row are a plan stored in the run; each piece is one job,
pieces run one after another and nothing is paid after a failed piece.
"""

from __future__ import annotations

import uuid
from typing import Any

from vf.core import db, jobs, pricing, settings
from vf.core.errors import AppError
from vf.modules.video import catalog, runs

MAX_STEPS = 10
MAX_TEXT = 2000
DOWNSCALE_TO = "1080p"


def tail_setting() -> float:
    return float(settings.get("video.extend_tail_seconds") or 10)


def source_of(run: dict) -> dict | None:
    """The current finished video of a run (files row), or None."""
    row = runs.file_row(run.get("result_file_id"))
    return row if row and row["kind"] == "video" else None


def source_seconds(run: dict, source: dict | None = None) -> float:
    source = source or source_of(run)
    if not source:
        return 0.0
    if source.get("duration"):
        return float(source["duration"])
    cur = runs.current_version(run)
    return float((cur or {}).get("duration") or run.get("duration") or 0)


def tail_seconds(m: dict, total: float) -> float:
    ceiling = catalog.max_input_seconds(m)
    tail = min(float(total), tail_setting(), ceiling) if ceiling > 0 else 0.0
    return round(max(tail, 0.0), 3)


def output_resolution(m: dict, source: dict | None) -> tuple[str, bool]:
    """Resolution of an extension: the source's, or the best the model has below it.
    ``True`` when the whole video gets smaller (e.g. a 4K source and a 1080p model)."""
    table = catalog.resolutions(m)
    names = sorted(table, key=catalog.resolution_rank)
    if not names:
        return "720p", False
    want = catalog.resolution_of_size((source or {}).get("width"), (source or {}).get("height"))
    if want in table:
        return want, False
    lower = [n for n in names if catalog.resolution_rank(n) < catalog.resolution_rank(want)]
    if lower:
        return lower[-1], True
    return names[0], False


def lengths(m: dict, resolution: str) -> list[int]:
    return catalog.durations(m, resolution)


def _other_model(run: dict, m: dict) -> bool:
    """The video was made by another kind of model: the picture may change slightly."""
    take_model = run.get("model_id")
    if not take_model:
        return False
    from vf.core import models_registry

    found = models_registry.find(take_model)
    return bool(found and found.get("api") != m.get("api"))


def info(run_id: int, model_id: str | None = None) -> dict:
    """Everything the extend panel shows before the button: can it, with what, how long, what size."""
    run = runs.get_run(run_id)
    source = source_of(run)
    out: dict[str, Any] = {
        "available": False, "reason": None, "models": [catalog.model_info(m) for m in catalog.extension_models()],
        "model_id": None, "tail_seconds": 0.0, "lengths": [], "resolution": None, "downscale": False,
        "source_seconds": source_seconds(run, source), "source_resolution": None, "other_model": False,
        "input_video": None, "busy": runs.active_job(run_id) is not None,
        "can_undo": (runs.current_version(run) or {}).get("kind") in ("extend", "continue"),
        "plan": run.get("extend_plan_json"), "continue_models": [catalog.model_info(m) for m in catalog.video_models()],
    }
    if source:
        out["source_resolution"] = catalog.resolution_of_size(source.get("width"), source.get("height"))
    try:
        m = catalog.extension_model(model_id)
    except AppError as err:
        out["reason"] = err.code
        return out
    res, downscale = output_resolution(m, source)
    out.update({
        "model_id": m["id"], "resolution": res, "downscale": downscale, "lengths": lengths(m, res),
        "tail_seconds": tail_seconds(m, out["source_seconds"]), "other_model": _other_model(run, m),
        "input_video": catalog.input_video_limits(m),
    })
    if not source:
        out["reason"] = "video_extend_no_video"
    elif out["busy"]:
        out["reason"] = "video_busy"
    else:
        out["available"] = True
    return out


def _check_steps(run: dict, m: dict, resolution: str, steps: list[dict]) -> list[dict]:
    if not steps:
        raise AppError("video_extend_no_steps", 400, "Add at least one piece")
    if len(steps) > MAX_STEPS:
        raise AppError("video_extend_too_many", 400, max=MAX_STEPS, count=len(steps))
    allowed = lengths(m, resolution)
    clean = []
    for i, step in enumerate(steps):
        text = str((step or {}).get("text") or "").strip()
        if len(text) > MAX_TEXT:
            raise AppError("video_text_too_long", 400, max=MAX_TEXT, step=i)
        if not text:
            text = (run.get("brief") or "").strip()  # empty "what next" = the brief of the video
        if not text:
            raise AppError("video_brief_empty", 400, "Describe the video first — the text is what gets filmed",
                           step=i)
        try:
            seconds = int((step or {}).get("seconds"))
        except (TypeError, ValueError):
            seconds = 0
        if seconds not in allowed:
            raise AppError("video_extend_length_unsupported", 400, seconds=seconds, allowed=allowed, step=i)
        clean.append({"text": text, "typed": bool(str((step or {}).get("text") or "").strip()), "seconds": seconds})
    return clean


def estimate(run_id: int, steps: list[dict], model_id: str | None = None) -> dict:
    """Worst case of each piece: the tail goes in and comes back with the new seconds."""
    run = runs.get_run(run_id)
    m = catalog.extension_model(model_id)
    source = source_of(run)
    res, downscale = output_resolution(m, source)
    total = source_seconds(run, source)
    pieces = []
    for step in steps or []:
        try:
            added = float((step or {}).get("seconds") or 0)
        except (TypeError, ValueError):
            added = 0.0
        tail = tail_seconds(m, total) if total else 0.0
        cost = pricing.estimate_video(m, seconds=tail + added, resolution=res, input_video_seconds=tail)
        total += added
        pieces.append({"seconds": added, "tail_seconds": tail, "estimate_usd": cost, "length_after": round(total, 3)})
    return {"model_id": m["id"], "resolution": res, "downscale": downscale, "pieces": pieces,
            "total_usd": round(sum(p["estimate_usd"] for p in pieces), 4), "length_after": round(total, 3),
            "source_seconds": source_seconds(run, source)}


def _plan_step(plan: dict, index: int) -> dict:
    return plan["steps"][index]


def enqueue_step(run_id: int, plan: dict, index: int) -> int:
    """Create the clip of piece ``index`` and queue its job. Saves the plan."""
    step = _plan_step(plan, index)
    run = runs.get_run(run_id)
    clip_id = runs.add_clip(run_id, kind="extend", model_id=plan["model_id"], prompt=None,
                            seconds=step["seconds"], resolution=plan.get("resolution"), next_text=step["text"],
                            seconds_added=step["seconds"], meta_json={"plan_id": plan["id"], "step": index,
                                                                      "typed": step.get("typed", True)})
    step.update({"status": "running", "clip_id": clip_id, "error_code": None, "error": None})
    plan["current"] = index
    plan["status"] = "running"
    runs.update_run_state(run_id, extend_plan_json=plan, stage="extend", status="running", error_code=None,
                          error=None)
    job_id = jobs.enqueue(runs.JOB_EXTEND, {"run_id": run_id, "clip_id": clip_id, "step": index},
                          ref_type=runs.SOURCE, ref_id=run_id, title=runs.job_title(run))
    runs.update_clip(clip_id, job_id=job_id)
    return clip_id


def start_extend(run_id: int, steps: list[dict], *, model_id: str | None = None,
                 pause_each: bool = True) -> dict:
    """Press "Extend" (one piece) or "Extend several times" (a list). Refusals before money."""
    run = runs.get_run(run_id)
    source = source_of(run)
    if not source:
        raise AppError("video_extend_no_video", 409, "Make the video first")
    runs.ensure_idle(run_id)
    m = catalog.extension_model(model_id)
    res, _downscale = output_resolution(m, source)
    clean = _check_steps(run, m, res, steps)
    plan = {
        "id": uuid.uuid4().hex[:12], "model_id": m["id"], "resolution": res, "mode": "extend",
        "pause_each": bool(pause_each), "status": "running", "current": 0, "created_at": db.now(),
        "steps": [{**s, "status": "pending", "clip_id": None, "version": None, "error_code": None, "error": None}
                  for s in clean],
    }
    enqueue_step(run_id, plan, 0)
    runs.publish(run_id)
    return runs.get_run(run_id)


def continue_plan(run_id: int, steps: list[dict] | None = None) -> dict:
    """"Next piece" after a pause, or retry after a stop/error. ``steps`` replaces the pieces not done yet."""
    run = runs.get_run(run_id)
    plan = dict(run.get("extend_plan_json") or {})
    if not plan or plan.get("status") not in ("paused", "stopped", "error"):
        raise AppError("video_extend_no_plan", 409, "There is nothing to continue")
    if not source_of(run):
        raise AppError("video_extend_no_video", 409, "Make the video first")
    runs.ensure_idle(run_id)
    m = catalog.extension_model(plan.get("model_id"))
    done = [s for s in plan["steps"] if s.get("status") == "done"]
    if steps is not None:
        rest = _check_steps(run, m, plan.get("resolution") or output_resolution(m, source_of(run))[0], steps)
        if len(done) + len(rest) > MAX_STEPS:
            raise AppError("video_extend_too_many", 400, max=MAX_STEPS, count=len(done) + len(rest))
        plan["steps"] = done + [{**s, "status": "pending", "clip_id": None, "version": None, "error_code": None,
                                 "error": None} for s in rest]
    index = next((i for i, s in enumerate(plan["steps"]) if s.get("status") != "done"), None)
    if index is None:
        plan["status"] = "done"
        runs.update_run_state(run_id, extend_plan_json=plan, status="done")
        runs.publish(run_id)
        return runs.get_run(run_id)
    enqueue_step(run_id, plan, index)
    runs.publish(run_id)
    return runs.get_run(run_id)


def drop_plan(run_id: int) -> dict:
    """Forget the pieces that were not made (the made ones stay as versions)."""
    run = runs.get_run(run_id)
    runs.ensure_idle(run_id)
    if run.get("extend_plan_json"):
        status = "done" if run.get("result_file_id") else "idle"
        runs.update_run_state(run_id, extend_plan_json=None, status=status)
    runs.publish(run_id)
    return runs.get_run(run_id)


def after_piece(run_id: int, index: int, *, ok: bool, version: int | None = None, error_code: str | None = None,
                error: str | None = None) -> str:
    """Record how piece ``index`` ended and decide what comes next: "next", "paused", "done", "stopped", "error"."""
    run = runs.get_run(run_id)
    plan = dict(run.get("extend_plan_json") or {})
    if not plan or index >= len(plan.get("steps") or []):
        return "done"
    step = plan["steps"][index]
    if not ok:
        step.update({"status": "error", "error_code": error_code, "error": error})
        plan["status"] = "error"
        runs.update_run_state(run_id, extend_plan_json=plan)
        return "error"
    step.update({"status": "done", "version": version})
    stopped = plan.get("status") == "stopped"
    more = any(s.get("status") != "done" for s in plan["steps"])
    if stopped:
        result = "stopped"
    elif not more:
        plan["status"] = "done"
        result = "done"
    elif plan.get("pause_each"):
        plan["status"] = "paused"
        result = "paused"
    else:
        result = "next"
    runs.update_run_state(run_id, extend_plan_json=plan,
                          status={"paused": "paused", "next": "running"}.get(result, "done"))
    if result == "next":
        nxt = next(i for i, s in enumerate(plan["steps"]) if s.get("status") != "done")
        enqueue_step(run_id, plan, nxt)
    return result


def mark_stopped(run_id: int, index: int | None) -> None:
    run = runs.get_run(run_id)
    plan = dict(run.get("extend_plan_json") or {})
    if not plan:
        return
    if index is not None and index < len(plan.get("steps") or []):
        if plan["steps"][index].get("status") != "done":
            plan["steps"][index]["status"] = "stopped"
    plan["status"] = "stopped"
    runs.update_run_state(run_id, extend_plan_json=plan)


# ── continue from the last frame ────────────────────────────────────────────


def continue_estimate(run_id: int, seconds: int, model_id: str | None = None) -> dict:
    run = runs.get_run(run_id)
    m = catalog.model(model_id or run.get("model_id"))
    source = source_of(run)
    res, downscale = output_resolution(m, source)
    fit = catalog.fit_settings(m, seconds=seconds, resolution=res, aspect=run.get("aspect"))
    return {"model_id": m["id"], "seconds": fit["duration"], "resolution": fit["resolution"],
            "aspect": fit["aspect"], "downscale": downscale,
            "estimate_usd": pricing.estimate_video(m, seconds=fit["duration"] or 0, resolution=fit["resolution"]),
            "length_after": round(source_seconds(run, source) + float(fit["duration"] or 0), 3)}


def start_continue(run_id: int, text: str, seconds: int, *, model_id: str | None = None) -> dict:
    """"Continue from the last frame": a new take that starts on the video's last frame."""
    run = runs.get_run(run_id)
    source = source_of(run)
    if not source:
        raise AppError("video_extend_no_video", 409, "Make the video first")
    runs.ensure_idle(run_id)
    m = catalog.model(model_id or run.get("model_id"))
    if not catalog.model_info(m)["first_frame"]:
        raise AppError("video_first_frame_unsupported", 400, model_id=m["id"])
    text = str(text or "").strip()
    if len(text) > MAX_TEXT:
        raise AppError("video_text_too_long", 400, max=MAX_TEXT)
    if not text:
        text = (run.get("brief") or "").strip()
    if not text:
        raise AppError("video_brief_empty", 400, "Describe the video first — the text is what gets filmed")
    res, _downscale = output_resolution(m, source)
    allowed = catalog.durations(m, res)
    if int(seconds or 0) not in allowed:
        raise AppError("video_extend_length_unsupported", 400, seconds=seconds, allowed=allowed)
    aspect = run.get("aspect")
    if aspect not in catalog.aspects(m):
        raise AppError("video_aspect_unsupported", 400, aspect=aspect, model_id=m["id"])
    clip_id = runs.add_clip(run_id, kind="continue", model_id=m["id"], prompt=text, seconds=int(seconds),
                            resolution=res, aspect=aspect, next_text=text, seconds_added=int(seconds),
                            source_version=run.get("current_version"), meta_json={"sound": bool(run.get("sound"))})
    runs.update_run_state(run_id, stage="extend", status="running", error_code=None, error=None)
    job_id = jobs.enqueue(runs.JOB_CONTINUE, {"run_id": run_id, "clip_id": clip_id}, ref_type=runs.SOURCE,
                          ref_id=run_id, title=runs.job_title(run))
    runs.update_clip(clip_id, job_id=job_id)
    runs.publish(run_id)
    return runs.get_run(run_id)


__all__ = [
    "MAX_STEPS", "after_piece", "continue_estimate", "continue_plan", "drop_plan", "enqueue_step", "estimate",
    "info", "mark_stopped", "output_resolution", "source_of", "source_seconds", "start_continue", "start_extend",
    "tail_seconds",
]
