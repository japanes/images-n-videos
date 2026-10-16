"""HTTP routes of the image studio (/api/studio/…). Contract: docs/dev/studio-api.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from vf.core.errors import AppError
from vf.modules.studio import export, generate, objects, sources
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_IMAGE_BYTES
from vf.modules.studio.estimate import estimate as estimate_body

router = APIRouter(prefix="/api/studio", tags=["studio"])


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    await file.close()
    if len(data) > limit:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=limit // 1024 // 1024)
    return data


def _frame(frame_id: int) -> dict:
    """The frame row, put in order first when its job is already over."""
    frame = W.frame_row(frame_id)
    if generate.settle(frame):
        frame = W.frame_row(frame_id)
    return frame


def _work(work_id: int) -> dict:
    W.work_row(work_id)
    generate.settle_work(work_id)
    return W.work_row(work_id)


def _ids(body: dict[str, Any]) -> list[int]:
    raw = body.get("ids")
    if not isinstance(raw, list):
        raise AppError("bad_order", 400, "ids must be a list of frame ids")
    try:
        return [int(x) for x in raw]
    except (TypeError, ValueError) as exc:
        raise AppError("bad_order", 400, "ids must be a list of frame ids") from exc


# ── works ───────────────────────────────────────────────────────────────────


@router.get("/works")
async def list_works(status: str = "active", q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    return W.list_works(status=status, q=q, limit=limit, offset=offset)


@router.post("/works")
async def create_work(body: dict[str, Any] | None = None) -> dict:
    return W.create_work(body or {})


@router.get("/works/{work_id}")
async def get_work(work_id: int) -> dict:
    _work(work_id)
    return W.get_work(work_id)


@router.patch("/works/{work_id}")
async def update_work(work_id: int, body: dict[str, Any]) -> dict:
    _work(work_id)
    return W.update_work(work_id, body)


@router.delete("/works/{work_id}")
async def delete_work(work_id: int) -> dict:
    _work(work_id)
    W.delete_work(work_id)
    return {"ok": True}


@router.post("/works/{work_id}/archive")
async def archive_work(work_id: int) -> dict:
    _work(work_id)
    return W.archive_work(work_id, True)


@router.post("/works/{work_id}/unarchive")
async def unarchive_work(work_id: int) -> dict:
    _work(work_id)
    return W.archive_work(work_id, False)


@router.post("/works/{work_id}/refresh-brand")
async def refresh_brand(work_id: int) -> dict:
    _work(work_id)
    return W.refresh_brand(work_id)


@router.get("/works/{work_id}/export")
async def export_work(work_id: int) -> Response:
    data, name = export.build_zip(work_id)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/works/{work_id}/generate")
async def generate_all(work_id: int) -> dict:
    _work(work_id)
    return generate.start_all(work_id)


@router.post("/works/{work_id}/accept-pilot")
async def accept_pilot(work_id: int) -> dict:
    _work(work_id)
    return generate.accept_pilot(work_id)


@router.post("/works/{work_id}/reorder")
async def reorder_frames(work_id: int, body: dict[str, Any]) -> dict:
    _work(work_id)
    return W.reorder_frames(work_id, _ids(body))


@router.post("/works/{work_id}/frames")
async def add_frame(work_id: int, body: dict[str, Any] | None = None) -> dict:
    after = (body or {}).get("after")
    try:
        after_id = int(after) if after not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise AppError("bad_request", 400, "after must be a frame id") from exc
    return W.add_frame(work_id, after=after_id)


# ── frames ──────────────────────────────────────────────────────────────────


@router.get("/frames/{frame_id}")
async def get_frame(frame_id: int) -> dict:
    return W.frame_public(_frame(frame_id))


@router.patch("/frames/{frame_id}")
async def update_frame(frame_id: int, body: dict[str, Any]) -> dict:
    _frame(frame_id)
    return W.update_frame(frame_id, body)


@router.delete("/frames/{frame_id}")
async def delete_frame(frame_id: int) -> dict:
    _frame(frame_id)
    return W.delete_frame(frame_id)


@router.post("/frames/{frame_id}/generate")
async def generate_frame(frame_id: int) -> dict:
    _frame(frame_id)
    return generate.start_frame(frame_id)


@router.post("/frames/{frame_id}/edit")
async def edit_frame(frame_id: int, body: dict[str, Any]) -> dict:
    _frame(frame_id)
    return generate.start_edit(frame_id, str(body.get("edit") or ""), body.get("region"))


@router.post("/frames/{frame_id}/cancel")
async def cancel_frame(frame_id: int) -> dict:
    _frame(frame_id)
    return generate.cancel_frame(frame_id)


@router.post("/frames/{frame_id}/find-objects")
async def find_objects(frame_id: int, body: dict[str, Any] | None = None) -> dict:
    _frame(frame_id)
    return await objects.find_objects(frame_id, (body or {}).get("focus") or "")


@router.post("/frames/{frame_id}/source")
async def upload_source(frame_id: int, file: UploadFile = File(...)) -> dict:
    _frame(frame_id)
    name = file.filename
    data = await _read(file, MAX_IMAGE_BYTES)
    return sources.upload_picture(frame_id, data, name)


@router.post("/frames/{frame_id}/pick")
async def pick_source(frame_id: int, body: dict[str, Any]) -> dict:
    _frame(frame_id)
    return sources.pick_picture(frame_id, body.get("file_id"), body.get("source") or "library",
                                body.get("source_ref"))


@router.post("/frames/{frame_id}/versions/{index}/restore")
async def restore_version(frame_id: int, index: int) -> dict:
    _frame(frame_id)
    return sources.restore_version(frame_id, index)


# ── price before the button ─────────────────────────────────────────────────


@router.post("/estimate")
async def estimate(body: dict[str, Any]) -> dict:
    return estimate_body(body)
