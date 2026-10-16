"""Clip projects: a source video plus the list of edits (``state_json``).

A project is opened for a video file (from the media library or from a chat
message). By default the newest project of that file is reopened, so the
"Edit" button does not pile up empty projects; ``new=True`` starts another one.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.modules.clip import export
from vf.modules.clip.state import empty_state, normalize, referenced_files

log = logging.getLogger("vf.clip.projects")

MAX_TITLE = 200
TRACK_KINDS = ("audio", "video")


# ── helpers ─────────────────────────────────────────────────────────────────

def _row(project_id: int) -> dict:
    row = db.get("clip_projects", project_id)
    if row is None:
        raise NotFound("clip project", id=project_id)
    return row


def _video_row(file_id: int) -> dict:
    row = db.get("files", int(file_id))
    if row is None:
        raise NotFound("file", id=file_id)
    if row["kind"] != "video":
        raise AppError("clip_not_video", 400, "Only a video can be opened in the clip editor", file_id=file_id)
    return row


def _default_title(row: dict) -> str:
    title = (row.get("title") or "").strip()
    if not title and row.get("original_name"):
        title = PurePosixPath(row["original_name"]).stem
    return (title or f"#{row['id']}")[:MAX_TITLE]


def _duration(row: dict) -> float | None:
    source = row.get("source_json") or {}
    value = source.get("duration")
    return float(value) if value else None


def _public_file(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    row = db.get("files", file_id)
    return files.public(row) if row else None


def _brand_changed(snap: dict | None) -> bool | None:
    if not snap:
        return None
    try:
        from vf.modules import brand
        return brand.kit_changed(snap)
    except Exception:  # noqa: BLE001 - a broken kit must not break the editor
        log.warning("brand kit check failed for clip project", exc_info=True)
        return None


def project_dict(row: dict) -> dict:
    """What the editor gets about a project."""
    exports = db.fetch_value("SELECT COUNT(*) FROM video_exports WHERE project_id = ?", (row["id"],), 0)
    return {
        "id": row["id"],
        "file_id": row["file_id"],
        "title": row["title"],
        "state": normalize(row.get("state_json") or {}, _duration(row)),
        "source": row.get("source_json") or {},
        "source_file": _public_file(row["file_id"]),
        "brand": row.get("brand_json"),
        "brand_changed": _brand_changed(row.get("brand_json")),
        "preview": _public_file(row.get("preview_file_id")),
        "status": row["status"],
        "exports_count": int(exports or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def summary_dict(row: dict) -> dict:
    """A short line for project lists."""
    return {"id": row["id"], "file_id": row["file_id"], "title": row["title"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


async def _probe(file_row: dict, saved: dict | None = None) -> dict:
    """Source facts; without ``render`` the editor still opens with what the file row knows."""
    try:
        return await export.probe_source(file_row, saved)
    except AppError as exc:
        if exc.code == "clip_not_video":
            raise
        log.info("render could not probe clip source %s: %s", file_row["id"], exc.code)
        return export.source_from_row(file_row, saved)


# ── API ─────────────────────────────────────────────────────────────────────

async def open_project(file_id: int, *, new: bool = False, title: str | None = None) -> dict:
    """The newest project of this video, or a fresh one."""
    file_row = _video_row(file_id)
    if not new:
        row = db.fetch_one("SELECT * FROM clip_projects WHERE file_id = ? ORDER BY id DESC LIMIT 1", (file_row["id"],))
        if row is not None:
            return await get_project(row["id"])
    source = await _probe(file_row)
    now = db.now()
    project_id = db.insert("clip_projects", {
        "file_id": file_row["id"],
        "title": (str(title).strip()[:MAX_TITLE] if title else "") or _default_title(file_row),
        "state_json": empty_state(),
        "source_json": source,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    })
    return project_dict(_row(project_id))


async def get_project(project_id: int) -> dict:
    row = _row(project_id)
    source = row.get("source_json") or {}
    if not source.get("duration") or source.get("has_audio") is None:
        file_row = db.get("files", row["file_id"])
        if file_row is not None:
            fresh = await _probe(file_row, source)
            if fresh != source:
                db.update("clip_projects", project_id, {"source_json": fresh})
                row = _row(project_id)
    return project_dict(row)


def list_projects(file_id: int | None = None, limit: int = 50) -> list[dict]:
    if file_id is not None:
        rows = db.fetch_all("SELECT * FROM clip_projects WHERE file_id = ? ORDER BY id DESC LIMIT ?",
                            (int(file_id), int(limit)))
    else:
        rows = db.fetch_all("SELECT * FROM clip_projects ORDER BY updated_at DESC, id DESC LIMIT ?", (int(limit),))
    return [summary_dict(r) for r in rows]


def check_files(state: dict, brand: dict | None = None) -> None:
    """Every file the edits point at exists and is of the right kind."""
    refs = referenced_files(state)
    wanted: list[tuple[int, tuple[str, ...]]] = (
        [(fid, TRACK_KINDS) for fid in refs["tracks"]]
        + [(fid, ("image",)) for fid in refs["images"]]
        + [(fid, ("font",)) for fid in refs["fonts"]]
    )
    for fid, kinds in wanted:
        row = db.get("files", fid)
        if row is None or row["kind"] not in kinds:
            raise AppError("clip_file_missing", 400, "A file used in the clip is missing or of the wrong kind",
                           file_id=fid, kinds=list(kinds))


def update_project(project_id: int, *, state: Any = None, title: str | None = None) -> dict:
    row = _row(project_id)
    values: dict[str, Any] = {}
    if state is not None:
        clean = normalize(state, _duration(row))
        check_files(clean)
        values["state_json"] = clean
    if title is not None:
        text = str(title).strip()[:MAX_TITLE]
        if not text:
            raise AppError("clip_title_empty", 400, "The title cannot be empty")
        values["title"] = text
    if values:
        values["updated_at"] = db.now()
        db.update("clip_projects", project_id, values)
    return project_dict(_row(project_id))


def set_brand(project_id: int, kit_id: int | None) -> dict:
    """Take a fresh snapshot of a brand kit (or drop it with ``None``)."""
    _row(project_id)
    snap = None
    if kit_id:
        from vf.modules import brand
        snap = brand.snapshot_kit(int(kit_id))
    db.update("clip_projects", project_id, {"brand_json": snap, "updated_at": db.now()})
    return project_dict(_row(project_id))


def refresh_brand(project_id: int) -> dict:
    row = _row(project_id)
    snap = row.get("brand_json") or {}
    if not snap.get("kit_id"):
        raise AppError("clip_no_brand", 400, "No brand kit is chosen for this clip")
    return set_brand(project_id, snap["kit_id"])


def delete_project(project_id: int) -> None:
    """Removes the project and its preview. Exported files stay in the media library."""
    row = _row(project_id)
    preview = row.get("preview_file_id")
    db.delete("clip_projects", project_id)
    if preview and db.get("files", preview) is not None:
        try:
            files.delete(preview, force=True)
        except AppError:
            log.warning("clip preview %s could not be deleted", preview)


def list_exports(project_id: int) -> list[dict]:
    _row(project_id)
    rows = db.fetch_all(
        "SELECT e.*, f.id AS present FROM video_exports e LEFT JOIN files f ON f.id = e.file_id "
        "WHERE e.project_id = ? ORDER BY e.id DESC", (project_id,))
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "job_id": r["job_id"], "part_index": r["part_index"], "part_count": r["part_count"],
            "width": r["width"], "height": r["height"], "duration": r["duration"],
            "params": r.get("params_json") or {}, "created_at": r["created_at"],
            "file": _public_file(r["file_id"]) if r["present"] else None,
        })
    return out
