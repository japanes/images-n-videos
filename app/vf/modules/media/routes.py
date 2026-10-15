"""HTTP routes of the media library (``/api/media/...``)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from vf.core import files
from vf.core.errors import AppError
from vf.modules.media import library, upload
from vf.modules.media.ingest import INGEST_KINDS, enqueue_video_ingest

router = APIRouter(prefix="/api/media")


@router.get("/limits")
async def get_limits() -> dict:
    return upload.limits()


@router.post("/upload")
async def post_upload(request: Request, kinds: str | None = None) -> dict:
    """Multipart: ``file`` (required) and ``title`` (optional text field).
    Query ``kinds`` (comma list) says what this screen accepts: default
    ``image,video,audio``; ``font`` only when asked for. It is a query parameter
    because the limits apply while the body is still arriving."""
    allowed = upload.parse_kinds(kinds)
    received = await upload.receive(request, allowed)
    row = await upload.store(received, title=received.fields.get("title"))
    job_id = enqueue_video_ingest(row["id"]) if row["kind"] in INGEST_KINDS else None
    out = library.item(files.get(row["id"]))
    out["ingest_job_id"] = job_id
    return out


@router.get("/files")
async def list_files(kind: str | None = None, source: str | None = None, q: str | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     page: int = Query(1, ge=1),
                     limit: int = Query(library.PAGE_SIZE, ge=1, le=library.MAX_PAGE_SIZE)) -> dict:
    return await asyncio.to_thread(library.list_files, kind=kind, source=source, q=q, date_from=date_from,
                                   date_to=date_to, page=page, limit=limit)


@router.get("/files/{file_id}")
async def get_file(file_id: int) -> dict:
    return library.item(library.get_library_row(file_id), with_usages=True)


class RenameBody(BaseModel):
    title: str | None = Field(None, max_length=1000)


@router.patch("/files/{file_id}")
async def patch_file(file_id: int, body: RenameBody) -> dict:
    return library.rename(file_id, body.title)


@router.delete("/files/{file_id}")
async def delete_file(file_id: int) -> dict:
    library.get_library_row(file_id)
    files.delete(file_id)
    return {"ok": True, "id": file_id}


class BulkDeleteBody(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)


@router.post("/files/delete")
async def delete_files(body: BulkDeleteBody) -> dict:
    return library.delete_many(body.ids)


@router.post("/files/{file_id}/ingest")
async def reingest(file_id: int) -> dict:
    row = library.get_library_row(file_id)
    if row["kind"] not in INGEST_KINDS:
        raise AppError("bad_request", 400, "only video and audio files are processed")
    return {"job_id": enqueue_video_ingest(file_id)}


@router.get("/stats")
async def get_stats() -> dict:
    return await asyncio.to_thread(library.stats)
