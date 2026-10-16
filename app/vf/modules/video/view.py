"""What the browser gets about a video run (also sent with every ``video.updated`` event)."""

from __future__ import annotations

from typing import Any

from vf.core import files
from vf.core.google import journal
from vf.modules.video import extend, generate, runs

RUN_FIELDS = ("id", "title", "niche", "platform", "brief", "model_id", "duration", "resolution", "aspect",
              "camera_move", "sound", "stage", "status", "error_code", "error", "current_version", "created_at",
              "updated_at")
CLIP_FIELDS = ("id", "number", "kind", "model_id", "prompt", "status", "seconds", "resolution", "aspect",
               "cost_usd", "error_code", "error", "next_text", "tail_seconds", "seconds_added", "seconds_received",
               "source_version", "created_at", "updated_at")


def _file(file_id: Any) -> dict | None:
    row = runs.file_row(file_id)
    return files.public(row) if row else None


def _clip(clip: dict) -> dict:
    out = {k: clip.get(k) for k in CLIP_FIELDS}
    meta = clip.get("meta_json") or {}
    out["warnings"] = list(meta.get("warnings") or [])
    out["file"] = _file(clip.get("file_id"))
    out["running"] = clip["status"] in ("queued", "running")
    return out


def _version(row: dict) -> dict:
    return {"number": row["number"], "kind": row["kind"], "duration": row.get("duration"),
            "clip_ids": list(row.get("clip_ids_json") or []), "file": _file(row["file_id"]),
            "created_at": row["created_at"]}


def _brief(run: dict) -> dict:
    meta = dict(run.get("brief_meta_json") or {})
    written_for = meta.get("seconds")
    return {
        "written": bool(meta.get("written_at")), "written_at": meta.get("written_at"),
        "written_for_seconds": written_for,
        "duration_changed": bool(written_for and run.get("duration") and int(written_for) != int(run["duration"])),
        "can_restore": bool(meta.get("replaced")), "camera_move_suggested": meta.get("camera_move_suggested"),
        "researched": bool(meta.get("researched")), "research_cached": bool(meta.get("research_cached")),
        "research_error": meta.get("research_error"), "cost_usd": meta.get("cost_usd"),
    }


def _storyboard(run: dict) -> dict | None:
    sb = runs.storyboard(run)
    if not sb.get("file_id"):
        return None
    return {**sb, "file": _file(sb["file_id"])}


def public_run(run_id: int) -> dict:
    generate.settle(run_id)
    run = runs.get_run(run_id)
    job = runs.active_job(run_id)
    out = {k: run.get(k) for k in RUN_FIELDS}
    out.update({
        "sound": bool(run.get("sound")),
        "first_frame": _file(run.get("first_frame_id")), "last_frame": _file(run.get("last_frame_id")),
        "references": [f for f in (_file(fid) for fid in runs.reference_ids(run)) if f],
        "result": _file(run.get("result_file_id")), "storyboard": _storyboard(run), "brief_info": _brief(run),
        "clips": [_clip(c) for c in runs.clips(run_id)],
        "versions": [_version(v) for v in runs.versions(run_id, include_archived=False)],
        "take": runs.take_preview(run), "extend": extend.info(run_id),
        "busy": job is not None, "job_id": job["id"] if job else None,
        "spent_usd": journal.cost_of(runs.SOURCE, run_id), "link": f"/chat?video={run_id}",
    })
    return out


def list_item(run: dict) -> dict:
    """One line of the list of videos."""
    result = _file(run.get("result_file_id"))
    cover = result or _file(run.get("first_frame_id"))
    return {"id": run["id"], "title": runs.job_title(run), "status": run.get("status"), "stage": run.get("stage"),
            "duration": run.get("duration"), "aspect": run.get("aspect"),
            "thumb_url": cover["thumb_url"] if cover else None, "updated_at": run.get("updated_at"),
            "link": f"/chat?video={run['id']}"}


__all__ = ["list_item", "public_run"]
