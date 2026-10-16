"""HTTP routes of the clip editor (/api/clip/...)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from vf.core import db, jobs
from vf.core.errors import AppError, NotFound
from vf.modules.clip import export, projects, subtitles, transcribe

router = APIRouter(prefix="/api/clip", tags=["clip"])

JOB_KINDS = (export.JOB_KIND, export.PREVIEW_KIND, transcribe.JOB_KIND)


def _int(body: dict[str, Any], key: str, *, required: bool = False) -> int | None:
    value = body.get(key)
    if value is None or value == "":
        if required:
            raise AppError("bad_request", 400, f"{key} is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AppError("bad_request", 400, f"{key} must be a number") from exc


def _project(project_id: int) -> dict:
    row = db.get("clip_projects", project_id)
    if row is None:
        raise NotFound("clip project", id=project_id)
    return row


# ── projects ────────────────────────────────────────────────────────────────

@router.post("/projects")
async def open_project(body: dict[str, Any]) -> dict:
    """Open the editor for a video: ``{file_id, new?, title?}``. Without ``new`` the
    newest project of that video is reopened."""
    file_id = _int(body, "file_id", required=True)
    return await projects.open_project(file_id, new=bool(body.get("new")), title=body.get("title"))


@router.get("/projects")
async def list_projects(file_id: int | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"items": projects.list_projects(file_id, limit)}


@router.get("/projects/{project_id}")
async def get_project(project_id: int) -> dict:
    return await projects.get_project(project_id)


@router.patch("/projects/{project_id}")
async def patch_project(project_id: int, body: dict[str, Any]) -> dict:
    title = body.get("title")
    return projects.update_project(project_id, state=body.get("state"),
                                   title=None if title is None else str(title))


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int) -> dict:
    projects.delete_project(project_id)
    return {"ok": True}


@router.put("/projects/{project_id}/brand")
async def set_brand(project_id: int, body: dict[str, Any]) -> dict:
    """``{kit_id}`` takes a fresh snapshot of the kit, ``{kit_id: null}`` drops it,
    ``{refresh: true}`` updates the snapshot from the same kit."""
    if body.get("refresh"):
        return projects.refresh_brand(project_id)
    return projects.set_brand(project_id, _int(body, "kit_id"))


@router.get("/presets")
async def list_presets() -> dict:
    return {"items": subtitles.list_presets()}


# ── export and preview ──────────────────────────────────────────────────────

async def _check_plan(project_id: int, *, preview: bool, parts: bool) -> dict:
    """Refuse at once what the job would refuse (nothing left, too many pieces...)."""
    row = _project(project_id)
    source_row = db.get("files", row["file_id"])
    if source_row is None:
        raise NotFound("file", id=row["file_id"])
    source = await export.probe_source(source_row, row.get("source_json"))
    plan = export.plan(row, source_row, source, preview=preview, parts=parts)
    return {"row": row, "plan": plan}


@router.post("/projects/{project_id}/export")
async def start_export(project_id: int, body: dict[str, Any] | None = None) -> dict:
    """``{parts: bool}`` — one file, or one file per split mark."""
    body = body or {}
    parts = bool(body.get("parts"))
    checked = await _check_plan(project_id, preview=False, parts=parts)
    plan = checked["plan"]
    job_id = export.enqueue(project_id, parts=parts, title=checked["row"]["title"])
    return {"job_id": job_id, "files": len(plan["parts"]) + 1 if plan["parts"] else 1,
            "duration": plan["duration"], "width": plan["width"], "height": plan["height"],
            "warnings": plan["burn"]["warnings"]}


@router.post("/projects/{project_id}/preview")
async def start_preview(project_id: int) -> dict:
    """A small, quick render to check the edits; replaces the previous preview."""
    checked = await _check_plan(project_id, preview=True, parts=False)
    job_id = export.enqueue(project_id, preview=True, title=checked["row"]["title"])
    return {"job_id": job_id}


@router.get("/projects/{project_id}/exports")
async def list_exports(project_id: int) -> dict:
    return {"items": projects.list_exports(project_id)}


@router.get("/projects/{project_id}/jobs")
async def list_jobs(project_id: int, active: bool = False) -> dict:
    _project(project_id)
    items = [j for j in jobs.list_jobs(active_only=active, ref_type="clip", ref_id=project_id, limit=30)
             if j["kind"] in JOB_KINDS]
    return {"items": items}


# ── subtitles from speech (local, free) ─────────────────────────────────────

@router.post("/projects/{project_id}/transcribe")
async def start_transcribe(project_id: int, body: dict[str, Any] | None = None) -> dict:
    """``{model?, language?, force?, replace?}`` — reuses a saved transcript unless ``force``;
    ``replace`` swaps the words already in the editor."""
    body = body or {}
    return transcribe.start(project_id, model=body.get("model"), language=body.get("language"),
                            force=bool(body.get("force")), replace=bool(body.get("replace")))


@router.get("/transcripts/{transcript_id}")
async def get_transcript(transcript_id: int) -> dict:
    return transcribe.get_transcript(transcript_id)


@router.get("/stt/models")
async def stt_models() -> dict:
    return await transcribe.models()


@router.post("/stt/models/{name}/download")
async def stt_download(name: str) -> dict:
    return await transcribe.download(name)


@router.delete("/stt/models/{name}")
async def stt_remove(name: str) -> dict:
    await transcribe.remove(name)
    return {"ok": True}


@router.get("/stt/estimate")
async def stt_estimate(model: str | None = None, project_id: int | None = None,
                       duration: float | None = Query(None, ge=0)) -> dict:
    """How long recognition is expected to take on this computer (for a project or a length)."""
    if project_id is not None and duration is None:
        duration = (_project(project_id).get("source_json") or {}).get("duration")
    return transcribe.estimate(transcribe.check_model(model), duration)
