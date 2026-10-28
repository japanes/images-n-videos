"""HTTP routes of the core: health, events, settings, jobs, models, estimates, files."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from vf.core import events, files, jobs, models_registry, pricing, settings
from vf.core.config import get_config
from vf.core.errors import AppError, NotFound
from vf.core.google import credentials

router = APIRouter()

THUMB_WIDTHS = (160, 320, 480, 640, 960, 1280, 1920)


# ── health and meta ─────────────────────────────────────────────────────────


@router.get("/health")
async def health() -> dict:
    cfg = get_config()
    return {"ok": True, "version": cfg.version, "google_mode": cfg.google_mode}


@router.get("/api/meta")
async def meta() -> dict:
    cfg = get_config()
    return {
        "version": cfg.version,
        "google_mode": cfg.google_mode,
        "stub": cfg.stub,
        "has_key": credentials.has_key(),
    }


@router.get("/api/events")
async def event_stream() -> StreamingResponse:
    return StreamingResponse(events.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── settings ────────────────────────────────────────────────────────────────


@router.get("/api/settings")
async def get_settings() -> dict:
    return {"values": settings.public_values(), "items": settings.describe()}


@router.put("/api/settings")
async def put_settings(body: dict[str, Any]) -> dict:
    defs = settings.definitions()
    for key in body:
        if key not in defs or not defs[key].public:
            raise AppError("unknown_setting", 400, key=key)
    for key, value in body.items():
        if value is None:
            settings.reset(key)
        else:
            settings.set(key, value)
    return {"values": settings.public_values(), "items": settings.describe()}


# ── jobs ────────────────────────────────────────────────────────────────────


@router.get("/api/jobs")
async def list_jobs(active: bool = False, ref_type: str | None = None, ref_id: int | None = None,
                    limit: int = Query(100, ge=1, le=500)) -> dict:
    return {"items": jobs.list_jobs(active_only=active, ref_type=ref_type, ref_id=ref_id, limit=limit)}


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: int) -> dict:
    return jobs.summary(jobs.get(job_id))


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: int) -> dict:
    return jobs.cancel(job_id)


@router.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: int) -> dict:
    return jobs.retry(job_id)


# ── models (registry lives in the core; module 02 adds checks and the UI) ───


class ModelPatch(BaseModel):
    enabled: bool | None = None
    is_default: bool | None = None
    user_price: dict | None = None
    reset_price: bool = False


@router.get("/api/models")
async def list_models(kind: str | None = None, include_removed: bool = False) -> dict:
    return {"items": models_registry.list_models(kind, include_removed=include_removed)}


@router.get("/api/models/roles")
async def list_roles() -> dict:
    return {"items": models_registry.roles_overview()}


class RolePatch(BaseModel):
    model_id: str | None = None


@router.put("/api/models/roles/{role}")
async def put_role(role: str, body: RolePatch) -> dict:
    models_registry.set_role_model(role, body.model_id)
    return {"items": models_registry.roles_overview()}


@router.patch("/api/models/{model_id}")
async def patch_model(model_id: str, body: ModelPatch) -> dict:
    model = models_registry.get(model_id)
    if body.is_default:
        model = models_registry.set_default(model_id)
    if body.enabled is not None:
        model = models_registry.set_enabled(model_id, body.enabled)
    if body.reset_price:
        model = models_registry.set_user_price(model_id, None)
    elif body.user_price is not None:
        model = models_registry.set_user_price(model_id, body.user_price)
    return model


# ── price before the button ─────────────────────────────────────────────────


class EstimateRequest(BaseModel):
    kind: str  # image | text | video
    model_id: str | None = None
    role: str | None = None
    count: int = 1
    image_size: str | None = None
    input_images: int = 0
    purpose: str | None = None
    search: bool = False
    seconds: float = 8
    resolution: str = "720p"
    input_video_seconds: float = 0


def estimate(req: EstimateRequest) -> dict:
    if req.kind == "image":
        model = models_registry.resolve("image", req.model_id)
        usd = pricing.estimate_image(model, count=req.count, image_size=req.image_size,
                                     input_images=req.input_images, purpose=req.purpose)
    elif req.kind == "text":
        model = (models_registry.resolve("text", req.model_id) if req.model_id or not req.role
                 else models_registry.model_for_role(req.role))
        usd = pricing.estimate_text(model, purpose=req.purpose, input_images=req.input_images,
                                    search=req.search, count=req.count)
    elif req.kind == "video":
        model = models_registry.resolve("video", req.model_id)
        usd = pricing.estimate_video(model, seconds=req.seconds, resolution=req.resolution, count=req.count,
                                     input_video_seconds=req.input_video_seconds)
    else:
        raise AppError("bad_request", 400, "kind must be image, text or video")
    return {"usd": usd, "model_id": model["id"]}


@router.post("/api/estimate")
async def post_estimate(body: EstimateRequest) -> dict:
    return estimate(body)


@router.post("/api/estimate/batch")
async def post_estimate_batch(body: list[EstimateRequest]) -> dict:
    items = [estimate(r) for r in body]
    return {"items": items, "usd": round(sum(i["usd"] for i in items), 4)}


# ── files ───────────────────────────────────────────────────────────────────


def _file_response(path: Path, mime: str | None, *, download_name: str | None = None,
                   immutable: bool = True) -> FileResponse:
    """A stored file never changes under its id, so the browser may keep it forever.
    Posters, hover previews and thumbnails made from a poster are rebuilt when a video
    is ingested again under the same id: those are revalidated (ETag) every time."""
    if not path.is_file():
        raise NotFound("file")
    headers = {"Cache-Control": "private, max-age=31536000, immutable" if immutable else "private, no-cache"}
    if download_name:
        return FileResponse(path, media_type=mime, filename=download_name, headers=headers)
    return FileResponse(path, media_type=mime, headers=headers)


def _thumb_path(row: dict, width: int) -> Path:
    width = next((w for w in THUMB_WIDTHS if w >= width), THUMB_WIDTHS[-1])
    target = files.data_dir() / "cache" / "thumbs" / str(row["id"]) / f"w{width}.webp"
    if target.is_file():
        return target
    source = files.abs_path(row["path"]) if row["kind"] == "image" else (
        files.abs_path(row["poster_path"]) if row.get("poster_path") else None)
    if source is None or not source.is_file():
        raise NotFound("thumbnail")
    from PIL import Image, ImageOps

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im)
        if im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        tmp = target.with_suffix(".part")
        im.save(tmp, "WEBP", quality=82)
        tmp.replace(target)
    return target


@router.get("/files/{file_id}")
async def serve_file(file_id: int, w: int | None = Query(None, ge=16, le=4096), download: bool = False):
    row = files.get(file_id)
    if w and (row["kind"] == "image" or row.get("poster_path")):
        path = await asyncio.to_thread(_thumb_path, row, w)
        return _file_response(path, "image/webp", immutable=row["kind"] == "image")
    name = None
    if download:
        name = row.get("original_name") or f"{row['kind']}-{row['id']}.{row.get('ext') or 'bin'}"
    return _file_response(files.abs_path(row["path"]), row["mime"], download_name=name)


@router.get("/files/{file_id}/poster")
async def serve_poster(file_id: int):
    row = files.get(file_id)
    if not row.get("poster_path"):
        raise NotFound("poster")
    path = files.abs_path(row["poster_path"])
    return _file_response(path, mimetypes.guess_type(path.name)[0] or "image/jpeg", immutable=False)


@router.get("/files/{file_id}/preview")
async def serve_preview(file_id: int):
    row = files.get(file_id)
    if not row.get("preview_path"):
        raise NotFound("preview")
    path = files.abs_path(row["preview_path"])
    return _file_response(path, mimetypes.guess_type(path.name)[0] or "video/mp4", immutable=False)


@router.get("/api/files/{file_id}")
async def file_info(file_id: int) -> dict:
    return files.public(files.get(file_id))


def spa_fallback(request: Request) -> Path | None:
    """index.html of the built frontend for any non-API path."""
    web_dir = get_config().web_dir
    if web_dir is None:
        return None
    rel = request.url.path.lstrip("/")
    candidate = (web_dir / rel).resolve() if rel else None
    root = web_dir.resolve()
    if candidate and candidate.is_file() and root in candidate.parents:
        return candidate
    index = web_dir / "index.html"
    return index if index.is_file() else None
