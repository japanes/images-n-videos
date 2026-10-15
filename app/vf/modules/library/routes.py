"""HTTP API of the style library: ``/api/library/...`` (the screen and the chat's style picker)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse

from vf.core.errors import AppError, NotFound
from vf.modules.library import service

router = APIRouter(prefix="/api/library", tags=["library"])


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    await file.close()
    if len(data) > limit:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=limit // 1024 // 1024)
    return data


@router.get("/categories")
async def get_categories(tab: str = "all", kind: str | None = None) -> dict:
    return service.category_tree(tab=tab, kind=kind or None)


@router.get("/styles")
async def list_styles(tab: str = "all", kind: str | None = None, category: str | None = None,
                      q: str | None = Query(None, max_length=service.MAX_QUERY_CHARS),
                      limit: int = Query(48, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    return service.list_styles(tab=tab, kind=kind or None, category=category or None, q=q, limit=limit,
                               offset=offset)


@router.get("/styles/random")
async def random_style(kind: str = "style", tab: str = "all", category: str | None = None,
                       exclude: int | None = None) -> dict:
    return {"item": service.random_style(kind=kind, tab=tab, category=category or None, exclude=exclude)}


@router.get("/styles/{style_id}")
async def get_style(style_id: int) -> dict:
    return service.get_style(style_id)


@router.post("/styles")
async def create_style(body: dict[str, Any]) -> dict:
    return service.create_style(body)


@router.patch("/styles/{style_id}")
async def update_style(style_id: int, body: dict[str, Any]) -> dict:
    return service.update_style(style_id, body)


@router.delete("/styles/{style_id}")
async def delete_style(style_id: int) -> dict:
    return service.delete_style(style_id)


@router.post("/styles/{style_id}/copy")
async def copy_style(style_id: int, body: dict[str, Any] | None = None) -> dict:
    title = (body or {}).get("title")
    return service.copy_style(style_id, title=None if title is None else str(title))


@router.post("/styles/{style_id}/preview")
async def upload_preview(style_id: int, file: UploadFile = File(...)) -> dict:
    data = await _read(file, service.MAX_PREVIEW_BYTES)
    return service.set_preview(style_id, data, file.filename)


@router.post("/styles/{style_id}/preview/from-file")
async def preview_from_file(style_id: int, body: dict[str, Any]) -> dict:
    try:
        file_id = int(body.get("file_id"))
    except (TypeError, ValueError) as exc:
        raise AppError("validation", 422, "file_id must be a number", field="file_id") from exc
    return service.set_preview_file(style_id, file_id)


@router.delete("/styles/{style_id}/preview")
async def remove_preview(style_id: int) -> dict:
    return service.remove_preview(style_id)


@router.get("/previews/{style_id}")
async def shipped_preview(style_id: int) -> FileResponse:
    path = service.seed_preview_file(style_id)
    # Revalidate (ETag / Last-Modified): an update may ship a new picture under the same id.
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.post("/render")
async def render(body: dict[str, Any]) -> dict:
    """Free, no AI: the style text with the slots filled, as it will join the prompt.
    Body: ``{style_id | ref, values?, extra?}``."""
    target = body.get("ref") if body.get("ref") is not None else body.get("style_id")
    result = service.render_style(target, body.get("values"),
                                  None if body.get("extra") is None else str(body.get("extra")))
    if result is None:
        raise NotFound("style")
    return result
