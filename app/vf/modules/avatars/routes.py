"""HTTP routes of the avatars (/api/avatars/…). Contract: docs/dev/avatars-api.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Response, UploadFile

from vf.core.errors import AppError
from vf.modules.avatars import catalog, draw, export, identity, photos, store
from vf.modules.avatars.estimate import estimate as estimate_avatar
from vf.modules.studio.common import MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/avatars", tags=["avatars"])


def _body(body: dict[str, Any] | None) -> dict[str, Any]:
    if body is not None and not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    return dict(body or {})


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError("file_too_large", 413, "The file is too large", max_mb=MAX_IMAGE_BYTES // 1024 // 1024)
    return data


# ── the list ────────────────────────────────────────────────────────────────

@router.get("")
async def list_avatars(archived: bool = False) -> dict:
    return store.list_avatars(archived=archived)


@router.get("/catalog")
async def get_catalog() -> dict:
    """The 36 shots and their categories (the wording sent with each shot)."""
    return catalog.public()


@router.post("")
async def create_avatar(body: dict[str, Any] | None = None) -> dict:
    return store.create(_body(body))


# ── one picture ─────────────────────────────────────────────────────────────

@router.patch("/photos/{photo_id}")
async def update_photo(photo_id: int, body: dict[str, Any] | None = None) -> dict:
    return photos.update_photo(photo_id, _body(body))


@router.delete("/photos/{photo_id}")
async def delete_photo(photo_id: int) -> dict:
    return photos.delete_photo(photo_id)


@router.post("/photos/{photo_id}/upload")
async def upload_to_slot(photo_id: int, file: UploadFile = File(...)) -> dict:
    data = await _read(file)
    return photos.upload_to_slot(photo_id, data, file.filename)


@router.post("/photos/{photo_id}/redraw")
async def redraw(photo_id: int) -> dict:
    return draw.redraw(photo_id)


@router.post("/photos/{photo_id}/fix")
async def fix(photo_id: int, body: dict[str, Any] | None = None) -> dict:
    return draw.fix(photo_id, _body(body).get("text"))


@router.post("/photos/{photo_id}/cancel")
async def cancel_photo(photo_id: int) -> dict:
    return draw.cancel(photo_id)


# ── one avatar ──────────────────────────────────────────────────────────────

@router.get("/{avatar_id}")
async def get_avatar(avatar_id: int) -> dict:
    return store.get(avatar_id)


@router.patch("/{avatar_id}")
async def update_avatar(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return store.update(avatar_id, _body(body))


@router.post("/{avatar_id}/archive")
async def archive_avatar(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return store.archive(avatar_id, bool(_body(body).get("archived", True)))


@router.post("/{avatar_id}/estimate")
async def estimate_action(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    # the package exports the function ``estimate`` under the submodule's name, hence the direct import
    return estimate_avatar(avatar_id, _body(body))


@router.get("/{avatar_id}/export")
async def export_pack(avatar_id: int) -> Response:
    data, name = export.build_zip(avatar_id)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# photos of the person (free)

@router.post("/{avatar_id}/photos")
async def upload_photo(avatar_id: int, file: UploadFile = File(...), angle: str = Form("")) -> dict:
    data = await _read(file)
    return photos.add_upload(avatar_id, data, file.filename, angle)


@router.post("/{avatar_id}/photos/from-files")
async def photos_from_files(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return photos.add_from_files(avatar_id, _body(body).get("file_ids"))


@router.post("/{avatar_id}/photos/order")
async def reorder_photos(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return photos.reorder(avatar_id, _body(body).get("ids"))


@router.post("/{avatar_id}/face")
async def make_face(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return photos.make_face(avatar_id, _body(body).get("photo_id"))


# the identity

@router.post("/{avatar_id}/describe")
async def describe(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return identity.start_describe(avatar_id, _body(body))


@router.post("/{avatar_id}/describe/cancel")
async def cancel_describe(avatar_id: int) -> dict:
    return identity.cancel_describe(avatar_id)


@router.put("/{avatar_id}/identity")
async def edit_identity(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return identity.edit_identity(avatar_id, _body(body))


@router.post("/{avatar_id}/identity/lock")
async def lock_identity(avatar_id: int) -> dict:
    return identity.lock(avatar_id)


@router.post("/{avatar_id}/identity/unlock")
async def unlock_identity(avatar_id: int) -> dict:
    return identity.unlock(avatar_id)


# drawing (paid)

@router.post("/{avatar_id}/candidates")
async def candidates(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return draw.start_candidates(avatar_id, _body(body))


@router.post("/{avatar_id}/pack")
async def pack(avatar_id: int, body: dict[str, Any] | None = None) -> dict:
    return draw.start_pack(avatar_id, _body(body).get("codes"))


@router.post("/{avatar_id}/finish")
async def finish(avatar_id: int) -> dict:
    return draw.finish(avatar_id)


@router.post("/{avatar_id}/cancel")
async def cancel_avatar(avatar_id: int) -> dict:
    return draw.cancel_avatar(avatar_id)
