"""Export of a clip project: a background job that asks ``render`` for a new
video file. The source file is never touched; every export is a new file in
the media library (source "export"), several files for an export "in parts".

The plan for render, in one ``compose`` job where possible:

- one kept piece -> ``compose {input, trim, crop?, burn?, mix?}``;
- several kept pieces (something removed in the middle) -> the source is first
  ``split`` at every piece border into scratch files, then
  ``compose {concat: kept pieces (hard cuts), crop?, burn?, mix?}``;
- "in parts" -> the composed clip goes to scratch and is ``split`` at the
  split marks into the final files.

A preview is the same plan at a small frame (longest side ``PREVIEW_MAX``),
saved as a service file that is replaced by the next preview.
"""

from __future__ import annotations

import logging
from typing import Any

from vf.core import db, events, files, jobs
from vf.core.errors import AppError
from vf.core.services import render
from vf.modules.clip import overlays
from vf.modules.clip.state import (
    normalize,
    output_duration,
    output_size,
    part_points,
    segments,
)

log = logging.getLogger("vf.clip.export")

JOB_KIND = "clip.export"
PREVIEW_KIND = "clip.preview"
PREVIEW_MAX = 960
MAX_PIECES = 24           # kept pieces; split takes at most 49 points (two per piece)
MAX_ASS_INLINE = 900_000  # bigger subtitles go to a scratch .ass file


# ── source ──────────────────────────────────────────────────────────────────

def source_from_row(row: dict, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    return {
        "duration": row.get("duration") or fallback.get("duration"),
        "width": row.get("width") or fallback.get("width"),
        "height": row.get("height") or fallback.get("height"),
        "has_audio": fallback.get("has_audio"),
    }


async def probe_source(row: dict, fallback: dict | None = None) -> dict:
    """Duration, upright size and whether there is sound. Asks ``render`` only
    when the file row and the saved project source do not know it."""
    source = source_from_row(row, fallback)
    if all(source[k] is not None for k in ("duration", "width", "height", "has_audio")):
        return source
    meta = await render.probe(row["path"]) or {}
    if not meta.get("has_video", True):
        raise AppError("clip_not_video", 400, "The file has no picture")
    duration = meta.get("duration")
    width = meta.get("display_width") or meta.get("width")
    height = meta.get("display_height") or meta.get("height")
    return {
        "duration": source["duration"] or (round(float(duration), 3) if duration else None),
        "width": source["width"] or (int(width) if width else None),
        "height": source["height"] or (int(height) if height else None),
        "has_audio": bool(meta.get("has_audio", True)),
    }


# ── plan ────────────────────────────────────────────────────────────────────

def _track_row(file_id: int) -> dict:
    row = db.get("files", file_id)
    if row is None or row["kind"] not in ("audio", "video"):
        raise AppError("clip_file_missing", 400, "A sound track file is missing", file_id=file_id)
    return row


def mix_step(state: dict, source_path: str, has_audio: bool = True) -> dict | None:
    """The ``mix`` step, or None when the sound stays as it is."""
    audio = state["audio"]
    has_voice = any(t["role"] == "voice" for t in audio["tracks"])
    tracks: list[dict[str, Any]] = []
    for t in audio["tracks"]:
        row = _track_row(t["file_id"])
        item: dict[str, Any] = {"input": row["path"], "role": t["role"], "volume": t["volume"],
                                "delay": t["delay"],
                                "duck": bool(t["duck"] and has_voice and t["role"] != "voice")}
        if t["fade_in"] > 0:
            item["fade_in"] = t["fade_in"]
        if t["fade_out"] > 0:
            item["fade_out"] = t["fade_out"]
        tracks.append(item)
    keep, volume = audio["keep_original"], audio["original_volume"]
    if not tracks:
        if keep and (abs(volume - 1.0) < 1e-6 or not has_audio):
            return None
        if keep:
            # render `mix` wants at least one track next to the original sound; a muted
            # copy of the source is the neutral one, so only the volume changes.
            tracks.append({"input": source_path, "role": "sfx", "volume": 0.0})
    return {"keep_original_audio": keep, "original_volume": volume, "tracks": tracks}


def plan(project: dict, source_row: dict, source: dict, *, preview: bool, parts: bool) -> dict:
    """What to send to render (without paths of scratch files)."""
    duration = float(source.get("duration") or 0)
    if duration <= 0:
        raise AppError("clip_no_duration", 400, "The length of the video is unknown")
    state = normalize(project.get("state_json") or {}, duration)
    segs = segments(state, duration)
    if not segs:
        raise AppError("clip_empty", 400, "Nothing is left of the video after the cuts")
    if len(segs) > MAX_PIECES:
        raise AppError("clip_too_many_pieces", 400, "Too many removed pieces", max=MAX_PIECES)
    width, height = output_size(state, source, preview=preview, preview_max=PREVIEW_MAX)
    burn = overlays.build_burn(state, segs, width=width, height=height, brand=project.get("brand_json"))
    crop = None
    if preview:
        crop = {"width": width, "height": height, "mode": state["crop"]["mode"]}
    elif state["crop"]["aspect"]:
        crop = {"aspect": state["crop"]["aspect"], "mode": state["crop"]["mode"]}
    return {
        "state": state,
        "segments": segs,
        "duration": output_duration(segs),
        "width": width,
        "height": height,
        "crop": crop,
        "burn": burn,
        "mix": mix_step(state, source_row["path"], source.get("has_audio") is not False),
        "parts": [] if preview or not parts else part_points(state, segs),
    }


def split_points(segs: list[tuple[float, float]], duration: float) -> list[float]:
    """Every border of a kept piece inside the source, for one ``split``."""
    points: set[float] = set()
    for a, b in segs:
        for p in (a, b):
            if 0.001 < p < duration - 0.001:
                points.add(round(p, 3))
    return sorted(points)


def kept_pieces(points: list[float], segs: list[tuple[float, float]], duration: float) -> list[int]:
    """Indexes of the split pieces that lie inside a kept piece."""
    bounds = [0.0, *points, duration]
    keep = []
    for i in range(len(bounds) - 1):
        mid = (bounds[i] + bounds[i + 1]) / 2
        if any(a <= mid <= b for a, b in segs):
            keep.append(i)
    return keep


def summary(p: dict) -> dict:
    """What an export did, kept in ``video_exports.params_json``."""
    state = p["state"]
    return {
        "width": p["width"], "height": p["height"], "duration": p["duration"],
        "segments": [[a, b] for a, b in p["segments"]],
        "aspect": state["crop"]["aspect"], "crop_mode": state["crop"]["mode"],
        "subtitles": bool(state["subtitles"]["enabled"] and state["subtitles"]["words"]),
        "preset": state["subtitles"]["preset_code"],
        "text_layers": sum(1 for x in state["layers"] if x["type"] == "text" and x["visible"]),
        "image_layers": sum(1 for x in state["layers"] if x["type"] == "image" and x["visible"]),
        "tracks": len(state["audio"]["tracks"]),
        "parts": len(p["parts"]) + 1 if p["parts"] else 1,
        "warnings": p["burn"]["warnings"],
    }


# ── job ─────────────────────────────────────────────────────────────────────

def enqueue(project_id: int, *, preview: bool = False, parts: bool = False, title: str | None = None) -> int:
    """A preview is its own job kind, so a newer preview can stop an older one."""
    if preview:
        for job in jobs.list_jobs(active_only=True, ref_type="clip", ref_id=project_id, limit=20):
            if job["kind"] == PREVIEW_KIND:
                jobs.cancel(job["id"])
    return jobs.enqueue(PREVIEW_KIND if preview else JOB_KIND,
                        {"project_id": project_id, "preview": preview, "parts": parts and not preview},
                        ref_type="clip", ref_id=project_id, title=title)


def _unlink(rel: str | None) -> None:
    if not rel:
        return
    try:
        files.abs_path(rel).unlink(missing_ok=True)
    except (AppError, OSError):
        pass


def _meta_size(meta: dict | None, p: dict) -> tuple[int, int, float]:
    meta = meta or {}
    width = meta.get("display_width") or meta.get("width") or p["width"]
    height = meta.get("display_height") or meta.get("height") or p["height"]
    duration = meta.get("duration") or p["duration"]
    return int(width), int(height), round(float(duration), 3)


def _publish(project_id: int, what: str, **extra: Any) -> None:
    events.publish("clip.updated", {"project_id": project_id, "what": what, **extra})


@jobs.handler(JOB_KIND, group="render", recover="interrupt")
async def run_export(ctx: jobs.JobContext) -> dict:
    project_id = int(ctx.payload["project_id"])
    preview = bool(ctx.payload.get("preview"))
    want_parts = bool(ctx.payload.get("parts"))
    project = db.get("clip_projects", project_id)
    if project is None:
        return {"project_id": project_id, "skipped": "deleted"}
    source_row = files.get(project["file_id"])
    source = await probe_source(source_row, project.get("source_json"))
    p = plan(project, source_row, source, preview=preview, parts=want_parts)
    ctx.raise_if_cancelled()

    scratch: list[str] = []
    finals: list[str] = []
    try:
        body: dict[str, Any] = {}
        segs = p["segments"]
        progress_from = 0.0
        if len(segs) == 1:
            a, b = segs[0]
            body["input"] = source_row["path"]
            body["trim"] = {"start": a, "end": b}
        else:
            points = split_points(segs, float(source["duration"]))
            pieces = [files.tmp_path("mp4")[0] for _ in range(len(points) + 1)]
            scratch.extend(pieces)
            await render.run("split", {"input": source_row["path"], "at": points, "outputs": pieces},
                             ctx=ctx, progress_from=0.0, progress_to=0.3, note="split")
            keep = kept_pieces(points, segs, float(source["duration"]))
            body["concat"] = {"inputs": [pieces[i] for i in keep], "transition": "cut"}
            progress_from = 0.3
        if p["crop"]:
            body["crop"] = p["crop"]
        burn = p["burn"]
        if burn["ass"] or burn["overlays"]:
            step: dict[str, Any] = {}
            if burn["overlays"]:
                step["overlays"] = burn["overlays"]
            if burn["ass"]:
                if len(burn["ass"].encode("utf-8")) > MAX_ASS_INLINE:
                    ass_rel, ass_abs = files.tmp_path("ass")
                    ass_abs.write_text(burn["ass"], encoding="utf-8")
                    scratch.append(ass_rel)
                    step["subtitles_path"] = ass_rel
                else:
                    step["subtitles_ass"] = burn["ass"]
                if burn["fonts"]:
                    step["fonts"] = burn["fonts"]
            body["burn"] = step
        if p["mix"]:
            body["mix"] = p["mix"]

        if p["parts"]:
            out_rel = files.tmp_path("mp4")[0]
            scratch.append(out_rel)
        else:
            out_rel = files.allocate("mp4")[0]
            finals.append(out_rel)
        body["output"] = out_rel
        result = await render.run("compose", body, ctx=ctx, progress_from=progress_from,
                                  progress_to=0.9 if p["parts"] else 1.0, note="compose")
        outputs: list[tuple[str, dict | None]] = [(result.get("output") or out_rel, result.get("meta"))]
        if p["parts"]:
            names = [files.allocate("mp4")[0] for _ in range(len(p["parts"]) + 1)]
            finals.extend(names)
            split = await render.run("split", {"input": out_rel, "at": p["parts"], "outputs": names},
                                     ctx=ctx, progress_from=0.9, progress_to=1.0, note="parts")
            outputs = [(o.get("output") or names[i], o.get("meta"))
                       for i, o in enumerate(split.get("outputs") or [])]
        ctx.raise_if_cancelled()

        if db.get("clip_projects", project_id) is None:  # deleted while render worked
            return {"project_id": project_id, "skipped": "deleted"}
        if preview:
            return _save_preview(project, outputs[0], p)
        return _save_exports(ctx, project, outputs, p)
    except BaseException:
        for rel in finals:
            _unlink(rel)
        raise
    finally:
        for rel in scratch:
            _unlink(rel)


@jobs.handler(PREVIEW_KIND, group="render", recover="interrupt")
async def run_preview(ctx: jobs.JobContext) -> dict:
    ctx.payload["preview"] = True
    ctx.payload["parts"] = False
    return await run_export(ctx)


def _save_preview(project: dict, output: tuple[str, dict | None], p: dict) -> dict:
    rel, meta = output
    width, height, duration = _meta_size(meta, p)
    row = files.register(rel, mime="video/mp4", origin="derived", service=True,
                         title=f"{project['title']} (preview)", source_type="clip_preview",
                         source_id=project["id"], width=width, height=height, duration=duration)
    old = project.get("preview_file_id")
    db.update("clip_projects", project["id"], {"preview_file_id": row["id"], "updated_at": db.now()})
    if old and old != row["id"] and db.get("files", old) is not None:
        try:
            files.delete(old, force=True)
        except AppError:
            log.warning("old clip preview %s could not be deleted", old)
    _publish(project["id"], "preview", file_id=row["id"])
    return {"project_id": project["id"], "preview_file_id": row["id"]}


def _save_exports(ctx: jobs.JobContext, project: dict, outputs: list[tuple[str, dict | None]], p: dict) -> dict:
    from vf.modules.media import enqueue_video_ingest

    count = len(outputs)
    params = summary(p)
    file_ids: list[int] = []
    rows: list[dict] = []
    for i, (rel, meta) in enumerate(outputs):
        width, height, duration = _meta_size(meta, p)
        title = project["title"] if count == 1 else f"{project['title']} ({i + 1}/{count})"
        rows.append(files.register(rel, mime="video/mp4", origin="derived", title=title,
                                   source_type="clip_export", source_id=project["id"],
                                   width=width, height=height, duration=duration))
    with db.tx():
        for i, row in enumerate(rows):
            db.insert("video_exports", {
                "project_id": project["id"], "file_id": row["id"], "job_id": ctx.id, "part_index": i,
                "part_count": count, "width": row["width"], "height": row["height"],
                "duration": row["duration"], "params_json": params, "created_at": db.now(),
            })
            file_ids.append(row["id"])
        db.update("clip_projects", project["id"], {"status": "exported", "updated_at": db.now()})
    for fid in file_ids:
        try:
            enqueue_video_ingest(fid)
        except AppError:
            log.warning("poster job for clip export %s was not queued", fid)
    _publish(project["id"], "exported", file_ids=file_ids)
    return {"project_id": project["id"], "file_ids": file_ids}
