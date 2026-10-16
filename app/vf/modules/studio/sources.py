"""Pictures that come from elsewhere (an upload, the media library, an avatar, a
video frame) and the frame's version history: going back to an earlier picture
is free and instant — nothing is sent to Google.
"""

from __future__ import annotations

from typing import Any

from vf.core import db, files
from vf.core.errors import AppError
from vf.modules.studio import generate
from vf.modules.studio import works as W
from vf.modules.studio.common import (
    BUSY,
    MAX_TITLE,
    SOURCE_UPLOAD,
    SOURCES,
    check_image,
    clean_text,
    image_file,
    publish,
)

PICKED_SOURCES = tuple(s for s in SOURCES if s != "generated")


def _check_free(frame: dict) -> None:
    if frame["status"] in BUSY:
        raise AppError("frame_busy", 409, "The frame is being drawn; wait or stop it")


def _source_ref(value: Any) -> dict | None:
    """Where a picked picture came from, e.g. ``{"avatar_id": 3}``: small, flat, plain values."""
    if not isinstance(value, dict):
        return None
    out = {}
    for key, v in list(value.items())[:8]:
        if isinstance(v, str | int | float | bool) or v is None:
            out[str(key)[:40]] = v if not isinstance(v, str) else v[:200]
    return out or None


def _put_picture(frame: dict, file_id: int, source: str, source_ref: dict | None) -> dict:
    with db.tx():
        current = W.frame_row(frame["id"])
        _check_free(current)
        version = {"file_id": file_id, "at": db.now(), "mode": "source", "prompt_text": None, "source": source,
                   "cost_usd": 0, "call_ids": [], "model_id": None, "image_size": None}
        db.update("frames", frame["id"], {
            "file_id": file_id, "clean_file_id": file_id, "source": source, "source_ref_json": source_ref,
            "status": "done", "error_code": None, "error_text": None, "drawing_since": None,
            "versions_json": generate.push_version(current, version), "updated_at": db.now(),
        })
        db.execute("UPDATE image_works SET status = 'active', updated_at = ? WHERE id = ? AND status = 'draft'",
                   (db.now(), frame["work_id"]))
    publish("frame", work_id=frame["work_id"], frame_id=frame["id"], status="done")
    return W.frame_public(W.frame_row(frame["id"]))


def upload_picture(frame_id: int, data: bytes, name: str | None) -> dict:
    """Put an uploaded picture into the frame (it is also kept in the media library)."""
    frame = W.frame_row(frame_id)
    _check_free(frame)
    mime = check_image(data, name)
    row = files.save_bytes(data, mime=mime, name=name or "picture", origin="upload", source_type=SOURCE_UPLOAD,
                           source_id=frame_id, title=clean_text(name, MAX_TITLE) or None)
    return _put_picture(frame, row["id"], "upload", None)


def pick_picture(frame_id: int, file_id: Any, source: Any = "library", source_ref: Any = None) -> dict:
    """Put a picture that is already stored into the frame."""
    frame = W.frame_row(frame_id)
    _check_free(frame)
    row = image_file(file_id)
    source = W.check_source(source or "library")
    if source not in PICKED_SOURCES:
        raise AppError("bad_request", 400, "Unknown picture source", source=source)
    return _put_picture(frame, row["id"], source, _source_ref(source_ref))


def restore_version(frame_id: int, index: Any) -> dict:
    """Show an earlier picture again (free). Its found objects come back with it."""
    with db.tx():
        frame = W.frame_row(frame_id)
        _check_free(frame)
        versions = frame.get("versions_json") or []
        try:
            i = int(index)
        except (TypeError, ValueError):
            i = -1
        if not 0 <= i < len(versions):
            raise AppError("version_unknown", 404, "There is no such version", index=index)
        v = versions[i]
        if not v.get("file_id") or db.get("files", v["file_id"]) is None:
            raise AppError("version_unknown", 404, "The picture of this version was deleted", index=i)
        values: dict[str, Any] = {
            "file_id": v["file_id"], "clean_file_id": v["file_id"], "status": "done", "error_code": None,
            "error_text": None, "prompt_text": v.get("prompt_text"), "source": v.get("source") or frame["source"],
            "updated_at": db.now(),
        }
        if v.get("objects"):
            values["objects_json"] = v["objects"]
            values["objects_sha"] = v["objects"].get("sha")
        db.update("frames", frame_id, values)
    publish("frame", work_id=frame["work_id"], frame_id=frame_id, status="done")
    return W.frame_public(W.frame_row(frame_id))
