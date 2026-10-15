"""HTTP routes of the connection screen and the first-run wizard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile

from vf.core.errors import AppError
from vf.modules.connection import service

router = APIRouter(prefix="/api/connection", tags=["connection"])


@router.get("")
async def get_state() -> dict:
    return service.state()


@router.put("")
async def put_marks(body: dict[str, Any]) -> dict:
    return service.update_marks(body)


@router.post("/key")
async def upload_key(file: UploadFile = File(...)) -> dict:
    raw = await file.read(service.MAX_KEY_BYTES + 1)
    await file.close()
    if len(raw) > service.MAX_KEY_BYTES:
        raise AppError("key_invalid", 400, reason="too_large", max_bytes=service.MAX_KEY_BYTES)
    return service.save_key(raw)


@router.delete("/key")
async def delete_key() -> dict:
    return service.delete_key()


@router.post("/check")
async def check() -> dict:
    return await service.run_basic_checks()


@router.post("/check/image")
async def check_image() -> dict:
    return await service.run_image_check()


@router.post("/check/omni")
async def check_omni() -> dict:
    return await service.run_omni_check()
