"""Video runs: one video being made. The brief, frames, references, settings, the
clips Google made for it and the versions of the finished video.

A version is a finished file. A take makes version 1; every extension or
"continue from the last frame" adds the next one built on the version that was
current. Rolling back is choosing another version (free). A new "Start" archives
the clips and versions of the previous take but keeps the brief, frames and
references.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from vf.core import db, events, files, jobs, models_registry, prompts
from vf.core.errors import AppError, NotFound
from vf.core.google.gateway import Blob, PromptInfo
from vf.modules.video import catalog

log = logging.getLogger("vf.video")

SOURCE = "video_run"  # files.source_type and the journal ref type
JOB_TAKE = "video.take"
JOB_EXTEND = "video.extend"
JOB_CONTINUE = "video.continue"
JOB_KINDS = (JOB_TAKE, JOB_EXTEND, JOB_CONTINUE)

STORYBOARD_NOTE = "video_storyboard_reference"  # library layer added when a sheet travels

DEFAULT_SECONDS = 8  # asked of the model when a run is created; snapped to what it allows
MAX_TITLE = 200
MAX_NICHE = 120
MAX_PLATFORM = 60
MAX_BRIEF = 4000
MAX_REFERENCES = 14
IMAGE_MIMES_SENT = ("image/png", "image/jpeg")

EDITABLE = ("title", "niche", "platform", "brief", "first_frame_id", "last_frame_id", "references",
            "model_id", "duration", "resolution", "aspect", "camera_move", "sound")


# ── reading ─────────────────────────────────────────────────────────────────


def get_run(run_id: int) -> dict:
    row = db.get("video_runs", run_id)
    if row is None:
        raise NotFound("video_run", id=run_id)
    return row


def get_clip(clip_id: int) -> dict:
    row = db.get("video_clips", clip_id)
    if row is None:
        raise NotFound("video_clip", id=clip_id)
    return row


def list_runs(limit: int = 50) -> list[dict]:
    return db.fetch_all("SELECT * FROM video_runs ORDER BY updated_at DESC, id DESC LIMIT ?", (int(limit),))


def clips(run_id: int, *, include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM video_clips WHERE run_id = ?"
    if not include_archived:
        sql += " AND archived = 0"
    return db.fetch_all(sql + " ORDER BY number, id", (run_id,))


def versions(run_id: int, *, include_archived: bool = True) -> list[dict]:
    sql = "SELECT * FROM video_versions WHERE run_id = ?"
    if not include_archived:
        sql += " AND archived = 0"
    return db.fetch_all(sql + " ORDER BY number", (run_id,))


def version(run_id: int, number: int | None) -> dict | None:
    if number is None:
        return None
    return db.fetch_one("SELECT * FROM video_versions WHERE run_id = ? AND number = ?", (run_id, int(number)))


def current_version(run: dict) -> dict | None:
    return version(run["id"], run.get("current_version"))


def file_row(file_id: int | None) -> dict | None:
    return db.get("files", int(file_id)) if file_id else None


def reference_ids(run: dict) -> list[int]:
    """References that still exist, in the user's order."""
    out: list[int] = []
    for fid in run.get("references_json") or []:
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        if fid not in out and file_row(fid) is not None:
            out.append(fid)
    return out


def storyboard(run: dict) -> dict:
    return dict(run.get("storyboard_json") or {})


def sheet_travels(run: dict) -> int | None:
    """The storyboard sheet file sent with the take, or None."""
    sb = storyboard(run)
    fid = sb.get("file_id")
    if sb.get("attached") and fid and file_row(fid) is not None:
        return int(fid)
    return None


def active_job(run_id: int) -> dict | None:
    rows = jobs.list_jobs(active_only=True, ref_type=SOURCE, ref_id=run_id, limit=5)
    rows = [r for r in rows if r["kind"] in JOB_KINDS]
    return rows[0] if rows else None


def ensure_idle(run_id: int) -> None:
    if active_job(run_id):
        raise AppError("video_busy", 409, "This video is being made; wait or press Stop", run_id=run_id)


def publish(run_id: int) -> None:
    """Tell the browser the run changed (the full public view goes with it)."""
    from vf.modules.video import view

    try:
        events.publish("video.updated", view.public_run(run_id))
    except NotFound:
        pass


# ── create / edit / delete ──────────────────────────────────────────────────


def _default_model() -> dict | None:
    try:
        return catalog.model(None)
    except AppError as err:
        if err.code in ("no_model", "model_unknown", "model_disabled"):
            return None
        raise


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if len(text) > limit:
        raise AppError("video_text_too_long", 400, "The text is too long", max=limit)
    return text


def _image_id(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        fid = int(value)
    except (TypeError, ValueError):
        raise AppError("video_frame_not_image", 400, "Pick a picture", file_id=value) from None
    row = files.get(fid)
    if row["kind"] != "image":
        raise AppError("video_frame_not_image", 400, "Pick a picture", file_id=fid)
    return fid


def create_run(values: dict | None = None) -> dict:
    values = dict(values or {})
    m = _default_model() if not values.get("model_id") else catalog.model(values["model_id"])
    fit = (catalog.fit_settings(m, seconds=DEFAULT_SECONDS, resolution=None, aspect=None)
           if m else {"duration": None, "resolution": None, "aspect": None})
    now = db.now()
    run_id = db.insert("video_runs", {
        "title": "", "model_id": m["id"] if m else None, "duration": fit["duration"],
        "resolution": fit["resolution"], "aspect": fit["aspect"], "sound": 1,
        "references_json": [], "results_json": [], "created_at": now, "updated_at": now,
    })
    if m and values.get("model_id") == m["id"]:
        values.pop("model_id")
    if values:
        try:
            update_run(run_id, values, notify=False)
        except AppError:
            db.delete("video_runs", run_id)
            raise
    publish(run_id)
    return get_run(run_id)


def update_run(run_id: int, values: dict, *, notify: bool = True) -> dict:
    """Autosave of the form. Unknown keys are refused; model changes snap the settings."""
    run = get_run(run_id)
    unknown = sorted(set(values) - set(EDITABLE))
    if unknown:
        raise AppError("video_field_unknown", 400, fields=unknown)
    out: dict[str, Any] = {}
    if "title" in values:
        out["title"] = _clean(values["title"], MAX_TITLE)
    if "niche" in values:
        out["niche"] = _clean(values["niche"], MAX_NICHE)
    if "platform" in values:
        out["platform"] = _clean(values["platform"], MAX_PLATFORM)
    if "brief" in values:
        out["brief"] = _clean(values["brief"], MAX_BRIEF)
    for key in ("first_frame_id", "last_frame_id"):
        if key in values:
            out[key] = _image_id(values[key])
    if "references" in values:
        refs: list[int] = []
        for v in values["references"] or []:
            fid = _image_id(v)
            if fid and fid not in refs:
                refs.append(fid)
        if len(refs) > MAX_REFERENCES:
            raise AppError("video_too_many_references", 400, max=MAX_REFERENCES, count=len(refs))
        out["references_json"] = refs
    if "camera_move" in values:
        out["camera_move"] = catalog.check_camera_move(values["camera_move"])
    if "sound" in values:
        out["sound"] = 1 if values["sound"] else 0

    model_id = values.get("model_id", run["model_id"]) or None
    shape_keys = {"model_id", "duration", "resolution", "aspect"} & set(values)
    if shape_keys:
        m = catalog.model(model_id)
        fit = catalog.fit_settings(
            m, seconds=values.get("duration", run["duration"]),
            resolution=values.get("resolution", run["resolution"]),
            aspect=values.get("aspect", run["aspect"]))
        out.update({"model_id": m["id"], "duration": fit["duration"], "resolution": fit["resolution"],
                    "aspect": fit["aspect"]})
    if out:
        out["updated_at"] = db.now()
        db.update("video_runs", run_id, out)
    if notify:
        publish(run_id)
    return get_run(run_id)


def delete_run(run_id: int) -> None:
    get_run(run_id)
    ensure_idle(run_id)
    db.delete("video_runs", run_id)
    events.publish("video.deleted", {"id": run_id})


# ── what goes to the model for a take ───────────────────────────────────────


def camera_sentence(code: str | None) -> str:
    phrase = catalog.clip_phrase(code).strip()
    if not phrase:
        return ""
    phrase = phrase[0].upper() + phrase[1:]
    return phrase if phrase.endswith((".", "!", "?")) else phrase + "."


def prompt_for_take(brief: str, camera_move: str | None, *, with_sheet: bool) -> str:
    """The brief verbatim, then the camera move, then the storyboard note."""
    parts = [brief.strip()]
    sentence = camera_sentence(camera_move)
    if sentence:
        parts.append(sentence)
    if with_sheet:
        from vf.modules import library

        parts.append(library.render_layer(STORYBOARD_NOTE, {}).strip())
    return "\n\n".join(p for p in parts if p)


def stage_one_take(run: dict) -> dict:
    """Everything a take needs, or the refusal (raised) before any money is spent."""
    brief = (run.get("brief") or "").strip()
    if not brief:
        raise AppError("video_brief_empty", 400, "Describe the video first — the text is what gets filmed")
    m = catalog.model(run.get("model_id"))
    info = catalog.model_info(m)
    fit = catalog.fit_settings(m, seconds=run.get("duration"), resolution=run.get("resolution"),
                               aspect=run.get("aspect"))
    models_registry.check_video_request(m, fit["duration"], fit["resolution"], fit["aspect"])

    first = run.get("first_frame_id") if file_row(run.get("first_frame_id")) else None
    last = run.get("last_frame_id") if file_row(run.get("last_frame_id")) else None
    if first and not info["first_frame"]:
        raise AppError("video_first_frame_unsupported", 400, model_id=m["id"])
    if last and not first:
        raise AppError("video_last_frame_needs_first", 400)
    if last and not info["last_frame"]:
        raise AppError("video_last_frame_unsupported", 400, model_id=m["id"])

    refs = reference_ids(run)
    sheet = sheet_travels(run)
    warnings: list[str] = []
    if first and info["frame_shadows_references"] and (refs or sheet):
        # With an opening frame this model ignores reference pictures: nothing else travels.
        warnings.append("frame_shadows_references")
        refs, sheet = [], None
    sent = refs + ([sheet] if sheet else [])
    if len(sent) > info["max_references"]:
        raise AppError("video_too_many_references", 400, max=info["max_references"], count=len(sent),
                       model_id=m["id"])

    prompt = prompt_for_take(brief, run.get("camera_move"), with_sheet=bool(sheet))
    prompt_info = None
    if sheet:
        prompt_info = PromptInfo(STORYBOARD_NOTE, prompts.get(STORYBOARD_NOTE).version)
    sound = True if not info["sound_switch"] else bool(run.get("sound"))
    return {
        "model": m, "prompt": prompt, "prompt_info": prompt_info, "seconds": int(fit["duration"]),
        "resolution": fit["resolution"], "aspect": fit["aspect"], "first_frame_id": first,
        "last_frame_id": last, "reference_ids": sent, "storyboard": bool(sheet), "sound": sound,
        "warnings": warnings,
    }


def take_preview(run: dict) -> dict:
    """What "Start" would send and cost, or why it cannot start (shown before pressing)."""
    try:
        staged = stage_one_take(run)
    except AppError as err:
        return {"ready": False, "refusal": err.code, "refusal_details": err.details, "prompt": None,
                "estimate_usd": None, "warnings": []}
    from vf.core import pricing

    m = staged["model"]
    return {
        "ready": True, "refusal": None, "refusal_details": {}, "prompt": staged["prompt"],
        "estimate_usd": pricing.estimate_video(m, seconds=staged["seconds"], resolution=staged["resolution"]),
        "warnings": staged["warnings"], "model_id": m["id"], "seconds": staged["seconds"],
        "resolution": staged["resolution"], "aspect": staged["aspect"], "sound": staged["sound"],
        "references_sent": len(staged["reference_ids"]), "storyboard": staged["storyboard"],
    }


# ── clips and versions ──────────────────────────────────────────────────────


def _next_number(table: str, run_id: int) -> int:
    return int(db.fetch_value(f"SELECT COALESCE(MAX(number), 0) FROM {table} WHERE run_id = ?", (run_id,), 0)) + 1


def add_clip(run_id: int, **values: Any) -> int:
    now = db.now()
    return db.insert("video_clips", {"run_id": run_id, "number": _next_number("video_clips", run_id),
                                     "status": "queued", "created_at": now, "updated_at": now, **values})


def update_clip(clip_id: int, **values: Any) -> None:
    db.update("video_clips", clip_id, {**values, "updated_at": db.now()})


def add_version(run_id: int, *, kind: str, file_id: int, duration: float | None, clip_ids: list[int]) -> int:
    """A new finished file; it becomes the current one."""
    number = _next_number("video_versions", run_id)
    now = db.now()
    db.insert("video_versions", {"run_id": run_id, "number": number, "kind": kind, "file_id": file_id,
                                 "duration": duration, "clip_ids_json": list(clip_ids), "created_at": now})
    run = get_run(run_id)
    history = list(run.get("results_json") or [])
    history.append({"file_id": file_id, "version": number, "kind": kind, "at": now})
    db.update("video_runs", run_id, {"current_version": number, "result_file_id": file_id,
                                     "results_json": history, "updated_at": now})
    return number


def update_run_state(run_id: int, **values: Any) -> None:
    db.update("video_runs", run_id, {**values, "updated_at": db.now()})


def start_take(run_id: int) -> dict:
    """Press "Start": refusals first, then archive the previous take and queue a new one."""
    run = get_run(run_id)
    ensure_idle(run_id)
    staged = stage_one_take(run)
    m = staged["model"]
    meta = {"first_frame_id": staged["first_frame_id"], "last_frame_id": staged["last_frame_id"],
            "reference_ids": staged["reference_ids"], "storyboard": staged["storyboard"],
            "sound": staged["sound"], "warnings": staged["warnings"],
            "prompt_code": staged["prompt_info"].code if staged["prompt_info"] else None,
            "prompt_version": staged["prompt_info"].version if staged["prompt_info"] else None}
    with db.tx():
        db.execute("UPDATE video_clips SET archived = 1, updated_at = ? WHERE run_id = ? AND archived = 0",
                   (db.now(), run_id))
        db.execute("UPDATE video_versions SET archived = 1 WHERE run_id = ? AND archived = 0", (run_id,))
        clip_id = add_clip(run_id, kind="take", model_id=m["id"], prompt=staged["prompt"],
                           seconds=staged["seconds"], resolution=staged["resolution"], aspect=staged["aspect"],
                           meta_json=meta)
        update_run_state(run_id, stage="take", status="running", error_code=None, error=None,
                         result_file_id=None, current_version=None, extend_plan_json=None,
                         model_id=m["id"], duration=staged["seconds"], resolution=staged["resolution"],
                         aspect=staged["aspect"])
    job_id = jobs.enqueue(JOB_TAKE, {"run_id": run_id, "clip_id": clip_id}, ref_type=SOURCE, ref_id=run_id,
                          title=job_title(run))
    update_clip(clip_id, job_id=job_id)
    publish(run_id)
    return get_run(run_id)


def job_title(run: dict) -> str:
    title = (run.get("title") or "").strip() or (run.get("brief") or "").strip().split("\n")[0]
    return (title[:60] + "…") if len(title) > 60 else (title or f"Video {run['id']}")


def choose_version(run_id: int, number: int) -> dict:
    """Roll back (or forward) to a version: free, nothing is regenerated."""
    get_run(run_id)
    ensure_idle(run_id)
    row = version(run_id, number)
    if row is None or row["archived"]:
        raise NotFound("video_version", run_id=run_id, number=number)
    update_run_state(run_id, current_version=row["number"], result_file_id=row["file_id"], status="done",
                     error_code=None, error=None)
    publish(run_id)
    return get_run(run_id)


def undo_last(run_id: int) -> dict:
    """"Undo last extension": back to the version it was built on; the undone one is archived."""
    run = get_run(run_id)
    ensure_idle(run_id)
    cur = current_version(run)
    if cur is None or cur["kind"] not in ("extend", "continue"):
        raise AppError("video_nothing_to_undo", 409, "There is no extension to undo")
    clip_ids = cur.get("clip_ids_json") or []
    clip, source = None, None
    if clip_ids:
        clip = db.get("video_clips", int(clip_ids[-1]))
        source = version(run_id, clip.get("source_version")) if clip else None
    if source is None or source["archived"]:
        live = [v for v in versions(run_id, include_archived=False) if v["number"] < cur["number"]]
        source = live[-1] if live else None
    if source is None:
        raise AppError("video_nothing_to_undo", 409, "There is no extension to undo")
    with db.tx():
        db.update("video_versions", cur["id"], {"archived": 1})
        if clip:
            update_clip(clip["id"], archived=1)
        update_run_state(run_id, current_version=source["number"], result_file_id=source["file_id"],
                         status="done", error_code=None, error=None)
    publish(run_id)
    return get_run(run_id)


def stop_run(run_id: int) -> dict:
    """Stop what is running for this video (and the rest of an extension plan)."""
    run = get_run(run_id)
    plan = dict(run.get("extend_plan_json") or {})
    if plan and plan.get("status") in ("running", "paused"):
        plan["status"] = "stopped"
        for step in plan.get("steps") or []:
            if step.get("status") == "running":
                step["status"] = "stopped"
        update_run_state(run_id, extend_plan_json=plan)
    job = active_job(run_id)
    if job:
        jobs.cancel(job["id"])
    # A queued job is cancelled without its handler running: settle its clips here.
    for clip in clips(run_id):
        if clip["status"] != "queued":
            continue
        row = db.get("jobs", clip["job_id"]) if clip.get("job_id") else None
        if row is None or row["status"] in ("cancelled", "error", "interrupted", "done"):
            update_clip(clip["id"], status="cancelled", error_code="cancelled")
    if not active_job(run_id):
        run = get_run(run_id)
        if run["status"] in ("running", "paused"):
            update_run_state(run_id, status="done" if run.get("result_file_id") else "idle")
    publish(run_id)
    return get_run(run_id)


# ── pictures sent to the model ──────────────────────────────────────────────


def image_blob(file_id: int, *, max_side: int | None = None) -> Blob:
    """A picture as the video model takes it: PNG or JPEG (WebP and others are converted)."""
    row = files.get(file_id)
    data = files.read_bytes(file_id)
    if row["mime"] in IMAGE_MIMES_SENT and not max_side:
        return Blob(data, row["mime"], file_id)
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        if max_side and max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
    return Blob(buf.getvalue(), "image/jpeg", file_id)


__all__ = [
    "JOB_CONTINUE", "JOB_EXTEND", "JOB_KINDS", "JOB_TAKE", "SOURCE", "active_job", "add_clip", "add_version",
    "camera_sentence", "choose_version", "clips", "create_run", "current_version", "delete_run", "ensure_idle",
    "get_clip", "get_run", "image_blob", "list_runs", "prompt_for_take", "publish", "reference_ids",
    "stage_one_take", "start_take", "stop_run", "take_preview", "undo_last", "update_clip", "update_run",
    "update_run_state", "version", "versions",
]
