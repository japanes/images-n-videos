"""HTTP routes of the brand screen: kits (/api/brand/kits…) and subjects (/api/brand/subjects…)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from vf.core.errors import AppError
from vf.modules.brand import describe, kits, subjects
from vf.modules.brand.common import MAX_FONT_BYTES, MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/brand", tags=["brand"])


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    await file.close()
    if len(data) > limit:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=limit // 1024 // 1024)
    return data


def _ids(body: dict[str, Any], key: str = "ids") -> list[int]:
    raw = body.get(key)
    if not isinstance(raw, list):
        raise AppError("bad_order", 400, f"{key} must be a list of ids")
    try:
        return [int(x) for x in raw]
    except (TypeError, ValueError) as exc:
        raise AppError("bad_order", 400, f"{key} must be a list of ids") from exc


def _opt_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    return None if value is None else str(value)


# ── kits ────────────────────────────────────────────────────────────────────


@router.get("/kits")
async def list_kits() -> dict:
    return {"items": kits.list_kits()}


@router.post("/kits")
async def create_kit(body: dict[str, Any]) -> dict:
    return kits.create_kit(str(body.get("name") or ""), colors=body.get("colors"), tone=str(body.get("tone") or ""))


@router.get("/kits/{kit_id}")
async def get_kit(kit_id: int) -> dict:
    return kits.get_kit(kit_id)


@router.patch("/kits/{kit_id}")
async def update_kit(kit_id: int, body: dict[str, Any]) -> dict:
    return kits.update_kit(kit_id, name=_opt_str(body, "name"), colors=body.get("colors"),
                           tone=_opt_str(body, "tone"))


@router.delete("/kits/{kit_id}")
async def delete_kit(kit_id: int) -> dict:
    kits.delete_kit(kit_id)
    return {"ok": True}


@router.get("/kits/{kit_id}/snapshot")
async def kit_snapshot(kit_id: int) -> dict:
    return kits.snapshot_kit(kit_id)


@router.post("/kits/{kit_id}/assets")
async def upload_asset(kit_id: int, file: UploadFile = File(...), kind: str = Form(...),
                       name: str | None = Form(None)) -> dict:
    data = await _read(file, MAX_IMAGE_BYTES)
    return kits.add_image_asset(kit_id, kind, data, filename=file.filename, name=name)


@router.post("/kits/{kit_id}/assets/from-file")
async def asset_from_file(kit_id: int, body: dict[str, Any]) -> dict:
    try:
        file_id = int(body.get("file_id"))
    except (TypeError, ValueError) as exc:
        raise AppError("bad_file", 400, "file_id is required") from exc
    return kits.add_image_asset_from_file(kit_id, str(body.get("kind") or ""), file_id, name=_opt_str(body, "name"))


@router.post("/kits/{kit_id}/fonts")
async def upload_font(kit_id: int, file: UploadFile = File(...)) -> dict:
    data = await _read(file, MAX_FONT_BYTES)
    return kits.add_font_upload(kit_id, data, filename=file.filename)


@router.put("/kits/{kit_id}/assets/order")
async def order_assets(kit_id: int, body: dict[str, Any]) -> dict:
    return {"items": kits.reorder_assets(kit_id, _ids(body))}


@router.patch("/assets/{asset_id}")
async def update_asset(asset_id: int, body: dict[str, Any]) -> dict:
    return kits.update_asset(asset_id, name=_opt_str(body, "name"), position_hint=_opt_str(body, "position_hint"),
                             note=_opt_str(body, "note"), kind=_opt_str(body, "kind"),
                             font_category=_opt_str(body, "font_category"))


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int) -> dict:
    kits.delete_asset(asset_id)
    return {"ok": True}


# ── subjects ────────────────────────────────────────────────────────────────


@router.get("/subjects")
async def list_subjects(scope: str = "library", q: str | None = None, kind: str | None = None) -> dict:
    return {"items": subjects.list_subjects(scope, q=q, kind=kind), "counts": subjects.counts(),
            "limits": {"photos": subjects.MAX_PHOTOS, "sent": subjects.PHOTOS_SENT,
                       "describe_photos": describe.MAX_PHOTOS}}


@router.post("/subjects")
async def create_subject(body: dict[str, Any]) -> dict:
    return subjects.create_subject(str(body.get("name") or ""), str(body.get("kind") or "product"),
                                   description=str(body.get("description") or ""),
                                   one_off=bool(body.get("one_off")))


@router.put("/subjects/order")
async def order_subjects(body: dict[str, Any]) -> dict:
    subjects.reorder_subjects(_ids(body))
    return {"ok": True}


@router.get("/subjects/{subject_id}")
async def get_subject(subject_id: int) -> dict:
    return subjects.get_subject(subject_id)


@router.patch("/subjects/{subject_id}")
async def update_subject(subject_id: int, body: dict[str, Any]) -> dict:
    cover = body.get("cover_file_id")
    return subjects.update_subject(
        subject_id, name=_opt_str(body, "name"), kind=_opt_str(body, "kind"),
        description=_opt_str(body, "description"), describe_focus=_opt_str(body, "describe_focus"),
        cover_file_id=None if cover is None else int(cover or 0))


@router.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: int) -> dict:
    subjects.delete_subject(subject_id)
    return {"ok": True}


@router.post("/subjects/{subject_id}/promote")
async def promote_subject(subject_id: int) -> dict:
    return subjects.promote_subject(subject_id)


@router.post("/subjects/{subject_id}/photos")
async def upload_photo(subject_id: int, file: UploadFile = File(...), angle: str | None = Form(None)) -> dict:
    data = await _read(file, MAX_IMAGE_BYTES)
    return subjects.add_photo_upload(subject_id, data, filename=file.filename, angle=angle or "")


@router.post("/subjects/{subject_id}/photos/from-files")
async def photos_from_files(subject_id: int, body: dict[str, Any]) -> dict:
    out = subjects.get_subject(subject_id)
    for file_id in _ids(body, "file_ids"):
        out = subjects.add_photo_from_file(subject_id, file_id)
    return out


@router.put("/subjects/{subject_id}/photos/order")
async def order_photos(subject_id: int, body: dict[str, Any]) -> dict:
    return subjects.reorder_photos(subject_id, _ids(body))


@router.patch("/subject-photos/{photo_id}")
async def update_photo(photo_id: int, body: dict[str, Any]) -> dict:
    return subjects.update_photo(photo_id, angle=_opt_str(body, "angle"))


@router.delete("/subject-photos/{photo_id}")
async def delete_photo(photo_id: int) -> dict:
    return subjects.delete_photo(photo_id)


@router.post("/subjects/{subject_id}/describe")
async def describe_subject(subject_id: int, body: dict[str, Any] | None = None) -> dict:
    body = body or {}
    return await describe.describe_subject(subject_id, force=bool(body.get("force")),
                                           focus=_opt_str(body, "focus"))
