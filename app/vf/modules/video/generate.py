"""Background jobs of a video: the take, one extension piece, a continuation from
the last frame.

Every Google call is linked to the run (``video_run``) and to its clip
(``video_clip``), so a clip's price is ``journal.cost_of("video_clip", id)``.

After a restart a job comes back (``recover="retry"``) and looks at its clip:

- the file is already saved → only the joining/saving is done again;
- a Veo operation is still open in the journal → the same operation is waited
  for again (nothing is paid twice);
- anything else that was in flight → the clip is closed as interrupted and the
  user decides whether to pay again. Nothing is re-sent silently.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from vf.core import db, files, jobs, prompts, settings
from vf.core.errors import AppError
from vf.core.google import GoogleCallError, journal
from vf.core.google import video as google_video
from vf.core.google.gateway import Blob, PromptInfo
from vf.core.services import render
from vf.modules.video import catalog, extend, runs

log = logging.getLogger("vf.video")

CLIP_REF = "video_clip"
EXTEND_PROMPT = "video.extend"
MIN_GAIN = 0.5  # an answer this much longer than the tail it got carries the tail too
SHORT_SIDE = {"720p": 720, "1080p": 1080, "4k": 2160}
INTERRUPTED = ("The app stopped while Google was making this clip. "
               "Start it again if you still want it (it will be paid again).")


def _serial(payload: dict) -> str:
    return f"video:{payload.get('run_id')}"


def _refs(run_id: int, clip_id: int) -> list[tuple[str, int]]:
    return [(runs.SOURCE, run_id), (CLIP_REF, clip_id)]


def clip_cost(clip_id: int) -> float:
    return journal.cost_of(CLIP_REF, clip_id)


def _ingest(file_id: int) -> None:
    """Poster, preview and exact length by the media module (best effort)."""
    try:
        from vf.modules.media import enqueue_video_ingest

        enqueue_video_ingest(file_id)
    except Exception:  # noqa: BLE001 - the video is saved either way
        log.warning("could not queue the media intake of file %s", file_id, exc_info=True)


def _unlink(*rels: str | None) -> None:
    for rel in rels:
        if rel:
            with suppress(AppError, OSError):
                files.abs_path(rel).unlink(missing_ok=True)


# ── clip bookkeeping ────────────────────────────────────────────────────────


def _clip_failed(run_id: int, clip_id: int, code: str, text: str) -> None:
    runs.update_clip(clip_id, status="error", error_code=code, error=text[:4000], cost_usd=clip_cost(clip_id))
    clip = runs.get_clip(clip_id)
    if clip["kind"] == "extend":
        step = (clip.get("meta_json") or {}).get("step")
        if step is not None:
            extend.after_piece(run_id, int(step), ok=False, error_code=code, error=text[:4000])
    runs.update_run_state(run_id, status="error", error_code=code, error=text[:4000])
    runs.publish(run_id)


def _clip_stopped(run_id: int, clip_id: int) -> None:
    runs.update_clip(clip_id, status="cancelled", error_code="cancelled", cost_usd=clip_cost(clip_id))
    clip = runs.get_clip(clip_id)
    if clip["kind"] == "extend":
        extend.mark_stopped(run_id, (clip.get("meta_json") or {}).get("step"))
    run = runs.get_run(run_id)
    runs.update_run_state(run_id, status="done" if run.get("result_file_id") else "idle",
                          stage=run["stage"] if run.get("result_file_id") else "draft")
    runs.publish(run_id)


async def _guarded(ctx: jobs.JobContext, run_id: int, clip_id: int, work) -> Any:
    """Run the work of a clip; on failure or Stop record it on the clip and the run."""
    try:
        return await work()
    except (asyncio.CancelledError, jobs.JobCancelled):
        if ctx.cancelled:
            _clip_stopped(run_id, clip_id)
        raise  # otherwise the app is stopping: the clip stays running and is resumed
    except GoogleCallError as err:
        _clip_failed(run_id, clip_id, err.code, err.raw or err.message)
        raise
    except AppError as err:
        _clip_failed(run_id, clip_id, err.code, err.message)
        raise
    except Exception as exc:
        _clip_failed(run_id, clip_id, "internal", str(exc) or exc.__class__.__name__)
        raise


def _live_clip(ctx: jobs.JobContext) -> tuple[int, dict] | None:
    run_id = int(ctx.payload["run_id"])
    clip = db.get("video_clips", int(ctx.payload["clip_id"]))
    if clip is None or clip["archived"] or clip["run_id"] != run_id or db.get("video_runs", run_id) is None:
        return None
    return run_id, clip


# ── one clip from Google ────────────────────────────────────────────────────


def _blobs(ids: list[int]) -> list[Blob]:
    return [runs.image_blob(fid) for fid in ids if runs.file_row(fid) is not None]


async def _shoot(ctx: jobs.JobContext, run_id: int, clip: dict, *, model: dict, prompt: str, seconds: int,
                 resolution: str, aspect: str | None, first_frame: Blob | None, last_frame: Blob | None,
                 references: list[Blob], sound: bool, purpose: str,
                 prompt_info: PromptInfo | None) -> google_video.VideoAnswer:
    """A new clip, or the open Veo operation of this clip after a restart."""
    clip_id = clip["id"]
    cancel = lambda: ctx.cancelled  # noqa: E731
    if clip["status"] == "running":
        row = journal.get_call(clip["call_id"]) if clip.get("call_id") else None
        if row and row["status"] == "running" and row.get("operation_name") and clip.get("operation_name"):
            log.info("video clip %s: waiting again for Veo operation %s", clip_id, row["operation_name"])
            return await google_video.wait_veo(clip["call_id"], cancel=cancel)
        raise AppError("video_interrupted", 409, INTERRUPTED)

    runs.update_clip(clip_id, status="running", error_code=None, error=None, call_id=None, operation_name=None)
    runs.update_run_state(run_id, status="running", error_code=None, error=None)
    runs.publish(run_id)
    common = {"model": model, "prompt": prompt, "seconds": int(seconds), "resolution": resolution,
              "first_frame": first_frame, "references": references, "purpose": purpose,
              "prompt_info": prompt_info, "refs": _refs(run_id, clip_id), "cancel": cancel}
    if model.get("api") == "omni":
        return await google_video.generate_omni(aspect=aspect, **common)

    def submitted(call_id: int, operation_name: str) -> None:
        runs.update_clip(clip_id, call_id=call_id, operation_name=operation_name)
        ctx.save_state(clip_id=clip_id, call_id=call_id, operation_name=operation_name)
        ctx.progress(0.2, force=True)

    return await google_video.generate_veo(aspect=aspect or "16:9", last_frame=last_frame, sound=sound,
                                           on_submitted=submitted, **common)


def _save_answer(run_id: int, clip_id: int, answer: google_video.VideoAnswer, *, service: bool,
                 title: str) -> dict:
    row = files.save_bytes(answer.data, mime=answer.mime or "video/mp4", name=f"video-{run_id}-{clip_id}.mp4",
                           origin="generated", service=service, title=title, source_type=runs.SOURCE,
                           source_id=run_id)
    runs.update_clip(clip_id, file_id=row["id"], call_id=answer.call_ids[-1] if answer.call_ids else None,
                     cost_usd=clip_cost(clip_id))
    return row


async def _probe(row: dict) -> dict:
    return await _probe_rel(row["path"])


async def _probe_rel(rel: str) -> dict:
    try:
        return await render.probe(rel) or {}
    except AppError:
        log.warning("could not probe %s", rel, exc_info=True)
        return {}


def _size(meta: dict) -> tuple[int | None, int | None]:
    w = meta.get("display_width") or meta.get("width")
    h = meta.get("display_height") or meta.get("height")
    return (int(w), int(h)) if w and h else (None, None)


def _seconds(meta: dict, fallback: float | None) -> float:
    try:
        value = float(meta.get("duration") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return round(value if value > 0 else float(fallback or 0), 3)


def _frame_size(width: int | None, height: int | None, resolution: str | None, downscale: bool) -> dict:
    """The size of a joined video: the source's, or smaller when the model cannot keep it."""
    if not width or not height:
        return {}
    if downscale and resolution in SHORT_SIDE:
        scale = SHORT_SIDE[resolution] / min(width, height)
        if scale < 1:
            width, height = width * scale, height * scale
    even = lambda v: max(16, int(round(v / 2)) * 2)  # noqa: E731
    return {"width": even(width), "height": even(height)}


def _register_result(rel: str, run: dict, kind: str, meta: dict, fallback_seconds: float) -> dict:
    width, height = _size(meta)
    return files.register(rel, mime="video/mp4", origin="generated", title=_title(run, kind),
                          source_type=runs.SOURCE, source_id=run["id"], width=width, height=height,
                          duration=_seconds(meta, fallback_seconds) or None)


def _title(run: dict, kind: str) -> str:
    base = runs.job_title(run)
    return base if kind == "take" else f"{base} ({kind})"


# ── the take ────────────────────────────────────────────────────────────────


@jobs.handler(runs.JOB_TAKE, group="video", serial_key=_serial, recover="retry")
async def run_take(ctx: jobs.JobContext) -> dict | None:
    found = _live_clip(ctx)
    if found is None:
        return {"skipped": "archived"}
    run_id, clip = found
    if clip["status"] == "done":
        return {"clip_id": clip["id"], "file_id": clip.get("file_id")}
    return await _guarded(ctx, run_id, clip["id"], lambda: _take(ctx, run_id, clip))


async def _take(ctx: jobs.JobContext, run_id: int, clip: dict) -> dict:
    run = runs.get_run(run_id)
    clip_id = clip["id"]
    meta = clip.get("meta_json") or {}
    if clip.get("file_id") and runs.file_row(clip["file_id"]):
        row = files.get(clip["file_id"])
    else:
        m = catalog.model(clip["model_id"])
        first = meta.get("first_frame_id")
        last = meta.get("last_frame_id")
        info = None
        if meta.get("prompt_code"):
            info = PromptInfo(meta["prompt_code"], int(meta.get("prompt_version") or 1))
        ctx.progress(0.05, force=True)
        answer = await _shoot(
            ctx, run_id, clip, model=m, prompt=clip["prompt"], seconds=clip["seconds"],
            resolution=clip["resolution"], aspect=clip["aspect"],
            first_frame=runs.image_blob(first) if first and runs.file_row(first) else None,
            last_frame=runs.image_blob(last) if last and runs.file_row(last) else None,
            references=_blobs(meta.get("reference_ids") or []), sound=bool(meta.get("sound", True)),
            purpose="video_take", prompt_info=info)
        row = _save_answer(run_id, clip_id, answer, service=False, title=_title(run, "take"))
    ctx.progress(0.9, force=True)
    probe = await _probe(row)
    width, height = _size(probe)
    duration = _seconds(probe, clip.get("seconds"))
    files.update(row["id"], {"duration": duration or None, "width": width or row.get("width"),
                             "height": height or row.get("height")})
    with db.tx():
        number = runs.add_version(run_id, kind="take", file_id=row["id"], duration=duration, clip_ids=[clip_id])
        runs.update_clip(clip_id, status="done", seconds_received=duration, cost_usd=clip_cost(clip_id),
                         error_code=None, error=None)
        runs.update_run_state(run_id, stage="done", status="done", error_code=None, error=None)
    _ingest(row["id"])
    runs.publish(run_id)
    return {"clip_id": clip_id, "file_id": row["id"], "version": number}


# ── one extension piece ─────────────────────────────────────────────────────


@jobs.handler(runs.JOB_EXTEND, group="video", serial_key=_serial, recover="retry")
async def run_extend(ctx: jobs.JobContext) -> dict | None:
    found = _live_clip(ctx)
    if found is None:
        return {"skipped": "archived"}
    run_id, clip = found
    if clip["status"] == "done":
        return {"clip_id": clip["id"], "file_id": clip.get("file_id")}
    return await _guarded(ctx, run_id, clip["id"], lambda: _extend(ctx, run_id, clip))


def _source_version(run: dict, clip: dict) -> dict:
    """The version a piece is built on (fixed on the clip at its first start)."""
    src = runs.version(run["id"], clip.get("source_version")) if clip.get("source_version") else None
    if src is None:
        src = runs.current_version(run)
        if src is None or runs.file_row(src["file_id"]) is None:
            raise AppError("video_extend_no_video", 409, "Make the video first")
        runs.update_clip(clip["id"], source_version=src["number"])
    if runs.file_row(src["file_id"]) is None:
        raise AppError("video_extend_no_video", 409, "Make the video first")
    return src


async def _cut(source_rel: str, start: float, end: float, frame: dict) -> str:
    """A stretch of the source as a fresh mp4 in the scratch folder (smaller if ``frame``)."""
    rel, _path = files.tmp_path("mp4")
    if frame:
        await render.run("compose", {"input": source_rel, "output": rel, "trim": {"start": start, "end": end},
                                     "crop": {**frame, "mode": "cover"}})
    else:
        await render.run("trim", {"input": source_rel, "output": rel, "start": start, "end": end})
    return rel


def _check_input(m: dict, rel: str) -> None:
    """Refusals about the attached video, before any money."""
    limits = catalog.input_video_limits(m)
    size = files.abs_path(rel).stat().st_size
    if size > limits["max_mb"] * 1024 * 1024:
        raise AppError("video_input_too_large", 400, max_mb=limits["max_mb"], size_mb=round(size / 1048576, 1))
    if "video/mp4" not in limits["mimes"]:
        raise AppError("video_extend_format", 400, mimes=limits["mimes"])


def _join_body(inputs: list[str], anchors: list[str | None], frame: dict, output: str) -> dict:
    fade = float(settings.get("video.extend_crossfade_seconds") or 0)
    body: dict[str, Any] = {"inputs": inputs, "output": output, **frame}
    if settings.get("video.extend_align"):
        body.update(transition="align", anchors=anchors, align_seconds=fade)
    elif fade > 0:
        body.update(transition="crossfade", transition_seconds=max(0.05, min(fade, 2.0)))
    else:
        body["transition"] = "cut"
    return body


async def _extend(ctx: jobs.JobContext, run_id: int, clip: dict) -> dict:
    run = runs.get_run(run_id)
    clip_id = clip["id"]
    step = int((clip.get("meta_json") or {}).get("step") or 0)
    m = catalog.extension_model(clip["model_id"])
    if clip["status"] == "running" and not clip.get("file_id"):
        raise AppError("video_interrupted", 409, INTERRUPTED)
    src_version = _source_version(run, clip)
    source = files.get(src_version["file_id"])
    resolution = clip.get("resolution") or extend.output_resolution(m, source)[0]
    _res, downscale = extend.output_resolution(m, source)
    src_meta = await _probe(source)
    total = _seconds(src_meta, src_version.get("duration") or source.get("duration"))
    width, height = _size(src_meta)
    frame = _frame_size(width or source.get("width"), height or source.get("height"), resolution, downscale)
    tail = extend.tail_seconds(m, total)
    if tail <= 0:
        raise AppError("video_extend_unsupported", 400, model_id=m["id"])
    head = round(max(0.0, total - tail), 3)
    scratch: list[str | None] = []
    try:
        if clip.get("file_id") and runs.file_row(clip["file_id"]):
            answer_row = files.get(clip["file_id"])
            tail = float(clip.get("tail_seconds") or tail)
            head = float(clip.get("tail_start") if clip.get("tail_start") is not None else head)
        else:
            ctx.progress(0.05, force=True)
            tail_rel = await _cut(source["path"], head, total, frame if downscale else {})
            scratch.append(tail_rel)
            _check_input(m, tail_rel)
            tail = _seconds(await _probe_rel(tail_rel), tail)
            runs.update_clip(clip_id, tail_start=head, tail_seconds=tail, source_version=src_version["number"])
            ctx.raise_if_cancelled()
            rendered = prompts.render(EXTEND_PROMPT, next=clip.get("next_text") or "")
            refs_ids = runs.reference_ids(run)[:catalog.max_references(m)]
            runs.update_clip(clip_id, prompt=rendered.text)
            clip = runs.get_clip(clip_id)
            ctx.progress(0.15, force=True)
            answer = await _shoot_extend(ctx, run_id, clip, m, rendered, resolution, tail, tail_rel, refs_ids)
            answer_row = _save_answer(run_id, clip_id, answer, service=True, title=_title(run, "extend"))
        ctx.progress(0.8, force=True)
        got = _seconds(await _probe(answer_row), float(clip.get("seconds_added") or 0) + tail)
        out_rel, _p = files.allocate("mp4")
        if got > tail + MIN_GAIN and head > 0.05:
            # The answer starts with the tail: keep the head and join on the frame at T - L.
            head_rel = await _cut(source["path"], 0, head, frame if downscale else {})
            anchor_rel, _a = files.tmp_path("jpg")
            scratch += [head_rel, anchor_rel]
            await render.frame(source["path"], anchor_rel, at=head)
            body = _join_body([head_rel, answer_row["path"]], [anchor_rel], frame, out_rel)
        elif got > tail + MIN_GAIN:
            # The whole video was the tail: the answer is the new video.
            body = {"inputs": [answer_row["path"]], "output": out_rel, "transition": "cut", **frame}
        else:
            # Only the new seconds came back: put them after the whole video.
            anchor_rel, _a = files.tmp_path("jpg")
            scratch.append(anchor_rel)
            await render.frame(source["path"], anchor_rel, at="last")
            body = _join_body([source["path"], answer_row["path"]], [anchor_rel], frame, out_rel)
        joined = await render.run("concat", body, ctx=ctx, progress_from=0.82, progress_to=0.97)
        meta = joined.get("meta") or await _probe_rel(out_rel)
        result = _register_result(out_rel, run, "extend", meta, total + float(clip.get("seconds_added") or 0))
    finally:
        _unlink(*scratch)
    return _finish_piece(run_id, clip_id, "extend", result, src_version, total, step)


async def _shoot_extend(ctx: jobs.JobContext, run_id: int, clip: dict, m: dict, rendered, resolution: str,
                        tail: float, tail_rel: str, refs_ids: list[int]) -> google_video.VideoAnswer:
    clip_id = clip["id"]
    if clip["status"] == "running":
        raise AppError("video_interrupted", 409, INTERRUPTED)
    runs.update_clip(clip_id, status="running", error_code=None, error=None)
    runs.update_run_state(run_id, status="running", error_code=None, error=None)
    runs.publish(run_id)
    added = int(clip.get("seconds_added") or clip.get("seconds") or 0)
    return await google_video.generate_omni(
        model=m, prompt=rendered.text, seconds=added, resolution=resolution, aspect=None,
        references=_blobs(refs_ids), input_video=Blob(files.abs_path(tail_rel).read_bytes(), "video/mp4"),
        input_video_seconds=tail, extend=True, bill_seconds=tail + added, purpose="video_extend",
        prompt_info=PromptInfo(rendered.code, rendered.version), refs=_refs(run_id, clip_id),
        cancel=lambda: ctx.cancelled)


def _finish_piece(run_id: int, clip_id: int, kind: str, result: dict, src_version: dict, before: float,
                  step: int | None) -> dict:
    duration = float(result.get("duration") or 0)
    clip_ids = list(src_version.get("clip_ids_json") or []) + [clip_id]
    with db.tx():
        number = runs.add_version(run_id, kind=kind, file_id=result["id"], duration=duration or None,
                                  clip_ids=clip_ids)
        runs.update_clip(clip_id, status="done", seconds_received=round(max(0.0, duration - before), 3),
                         cost_usd=clip_cost(clip_id), error_code=None, error=None)
        if kind == "extend" and step is not None:
            extend.after_piece(run_id, step, ok=True, version=number)
        else:
            runs.update_run_state(run_id, stage="done", status="done", error_code=None, error=None)
    _ingest(result["id"])
    runs.publish(run_id)
    return {"clip_id": clip_id, "file_id": result["id"], "version": number}


# ── continue from the last frame ────────────────────────────────────────────


@jobs.handler(runs.JOB_CONTINUE, group="video", serial_key=_serial, recover="retry")
async def run_continue(ctx: jobs.JobContext) -> dict | None:
    found = _live_clip(ctx)
    if found is None:
        return {"skipped": "archived"}
    run_id, clip = found
    if clip["status"] == "done":
        return {"clip_id": clip["id"], "file_id": clip.get("file_id")}
    return await _guarded(ctx, run_id, clip["id"], lambda: _continue(ctx, run_id, clip))


async def _last_frame(run_id: int, clip: dict, source: dict) -> dict:
    """The last frame of the source as a picture file (kept on the clip)."""
    meta = dict(clip.get("meta_json") or {})
    fid = meta.get("first_frame_id")
    if fid and runs.file_row(fid):
        return files.get(fid)
    rel, _p = files.allocate("jpg")
    await render.frame(source["path"], rel, at="last")
    row = files.register(rel, mime="image/jpeg", origin="generated", service=True, title="Last frame",
                         source_type=runs.SOURCE, source_id=run_id)
    meta["first_frame_id"] = row["id"]
    runs.update_clip(clip["id"], meta_json=meta)
    return row


async def _continue(ctx: jobs.JobContext, run_id: int, clip: dict) -> dict:
    run = runs.get_run(run_id)
    clip_id = clip["id"]
    m = catalog.model(clip["model_id"])
    src_version = _source_version(run, clip)
    source = files.get(src_version["file_id"])
    _res, downscale = extend.output_resolution(m, source)
    src_meta = await _probe(source)
    total = _seconds(src_meta, src_version.get("duration") or source.get("duration"))
    width, height = _size(src_meta)
    frame = _frame_size(width or source.get("width"), height or source.get("height"), clip.get("resolution"),
                        downscale)
    still = await _last_frame(run_id, clip, source)
    clip = runs.get_clip(clip_id)
    if clip.get("file_id") and runs.file_row(clip["file_id"]):
        piece = files.get(clip["file_id"])
    else:
        info = catalog.model_info(m)
        refs = [] if info["frame_shadows_references"] else runs.reference_ids(run)[:info["max_references"]]
        ctx.progress(0.1, force=True)
        answer = await _shoot(
            ctx, run_id, clip, model=m, prompt=clip["prompt"], seconds=clip["seconds"],
            resolution=clip["resolution"], aspect=clip["aspect"], first_frame=runs.image_blob(still["id"]),
            last_frame=None, references=_blobs(refs), sound=bool((clip.get("meta_json") or {}).get("sound", True)),
            purpose="video_continue", prompt_info=None)
        piece = _save_answer(run_id, clip_id, answer, service=True, title=_title(run, "continue"))
    ctx.progress(0.8, force=True)
    out_rel, _p = files.allocate("mp4")
    body = _join_body([source["path"], piece["path"]], [still["path"]], frame, out_rel)
    joined = await render.run("concat", body, ctx=ctx, progress_from=0.82, progress_to=0.97)
    meta = joined.get("meta") or await _probe_rel(out_rel)
    result = _register_result(out_rel, run, "continue", meta, total + float(clip.get("seconds") or 0))
    return _finish_piece(run_id, clip_id, "continue", result, src_version, total, None)


# ── after a restart ─────────────────────────────────────────────────────────


def sweep() -> None:
    """Clips left queued/running whose job is gone: resume an open Veo operation with a
    new job, close the rest as interrupted. Jobs still queued/running come back by themselves."""
    rows = db.fetch_all("SELECT * FROM video_clips WHERE archived = 0 AND status IN ('queued', 'running')")
    for clip in rows:
        job = db.get("jobs", clip["job_id"]) if clip.get("job_id") else None
        if job and job["status"] in jobs.ACTIVE:
            continue
        call = journal.get_call(clip["call_id"]) if clip.get("call_id") else None
        run = db.get("video_runs", clip["run_id"])
        if run is None:
            continue
        kind = {"take": runs.JOB_TAKE, "extend": runs.JOB_EXTEND, "continue": runs.JOB_CONTINUE}[clip["kind"]]
        if (clip["status"] == "running" and call and call["status"] == "running" and call.get("operation_name")):
            payload = {"run_id": clip["run_id"], "clip_id": clip["id"]}
            if clip["kind"] == "extend":
                payload["step"] = (clip.get("meta_json") or {}).get("step")
            job_id = jobs.enqueue(kind, payload, ref_type=runs.SOURCE, ref_id=clip["run_id"],
                                  title=runs.job_title(run))
            runs.update_clip(clip["id"], job_id=job_id)
            continue
        code = "cancelled" if clip["status"] == "queued" else "video_interrupted"
        runs.update_clip(clip["id"], status="cancelled" if code == "cancelled" else "error", error_code=code,
                         error=None if code == "cancelled" else INTERRUPTED, cost_usd=clip_cost(clip["id"]))
        if run["status"] in ("running", "paused") and not runs.active_job(run["id"]):
            if code == "cancelled":
                runs.update_run_state(run["id"], status="done" if run.get("result_file_id") else "idle")
            else:
                runs.update_run_state(run["id"], status="error", error_code=code, error=INTERRUPTED)


async def take_frame(run_id: int, at: float | str = "last", version: int | None = None) -> dict:
    """"Take frame": one picture from a version of the video, saved to the media library (free)."""
    run = runs.get_run(run_id)
    row = runs.version(run_id, version) if version else runs.current_version(run)
    source = runs.file_row(row["file_id"]) if row else runs.file_row(run.get("result_file_id"))
    if source is None:
        raise AppError("video_extend_no_video", 409, "There is no video yet")
    if isinstance(at, str):
        if at not in ("first", "last"):
            raise AppError("video_frame_at", 400, at=at)
        label = at
    else:
        at = max(0.0, float(at))
        if source.get("duration"):
            at = min(at, float(source["duration"]))
        label = f"{at:.2f} s"
    rel, _p = files.allocate("jpg")
    await render.frame(source["path"], rel, at=at)
    saved = files.register(rel, mime="image/jpeg", origin="generated", title=f"{runs.job_title(run)} · {label}",
                           source_type=runs.SOURCE, source_id=run_id,
                           meta={"from_file_id": source["id"], "at": at})
    return files.public(saved)


def settle(run_id: int) -> None:
    """A queued clip whose job was cancelled elsewhere (e.g. on the jobs screen) is closed."""
    for clip in db.fetch_all("SELECT * FROM video_clips WHERE run_id = ? AND archived = 0 AND status = 'queued'",
                             (run_id,)):
        job = db.get("jobs", clip["job_id"]) if clip.get("job_id") else None
        if job is not None and job["status"] in ("cancelled", "error", "interrupted"):
            runs.update_clip(clip["id"], status="cancelled", error_code="cancelled")
            run = runs.get_run(run_id)
            if run["status"] == "running" and not runs.active_job(run_id):
                runs.update_run_state(run_id, status="done" if run.get("result_file_id") else "idle")


__all__ = ["CLIP_REF", "clip_cost", "run_continue", "run_extend", "run_take", "settle", "sweep", "take_frame"]
