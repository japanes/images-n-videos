"""The media library: which files the person sees, where they are used, how much
space they take.

The library shows files that are not service files (``is_service = 0``) and are
pictures, videos or sounds. Fonts and other kinds live in their own screens
(brand kits) but use the same upload and delete rules.

Source group of a file (the "source" filter), from ``origin`` and ``source_type``:

- ``upload``     — ``origin = 'upload'``;
- ``avatar``     — ``source_type`` starts with ``avatar``;
- ``export``     — ``source_type`` contains ``export`` (finished video exports);
- ``editor``     — ``source_type`` starts with ``editor`` or ``origin = 'derived'``
                   (trimmed, cropped, assembled from other files);
- ``generation`` — everything else (Google results).
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.modules.media.ingest import ingest_state
from vf.modules.media.upload import LIBRARY_KINDS, MAX_TITLE, clean_title

log = logging.getLogger("vf.media.library")

PAGE_SIZE = 40
MAX_PAGE_SIZE = 200
SOURCE_GROUPS = ("upload", "generation", "avatar", "editor", "export")
SOURCE_SQL = (
    "CASE WHEN origin = 'upload' THEN 'upload' "
    "WHEN source_type LIKE 'avatar%' THEN 'avatar' "
    "WHEN source_type LIKE '%export%' THEN 'export' "
    "WHEN source_type LIKE 'editor%' OR origin = 'derived' THEN 'editor' "
    "ELSE 'generation' END"
)


def _split(value: str | None, allowed: tuple[str, ...], what: str) -> list[str]:
    if not value:
        return []
    items = list(dict.fromkeys(v.strip().lower() for v in value.split(",") if v.strip()))
    bad = [v for v in items if v not in allowed]
    if bad:
        raise AppError("bad_request", 400, f"unknown {what}", values=bad)
    return items


def normalize_ts(value: str | None, name: str) -> str | None:
    """An ISO date or timestamp from the browser -> the database time format (UTC)."""
    if not value:
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
    except ValueError as exc:
        raise AppError("bad_request", 400, f"{name} is not a date", field=name) from exc
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def safe_usages(file_id: int) -> list[dict] | None:
    """Usages for display; ``None`` when a module failed to answer (deletion is
    then refused by ``files.delete`` itself)."""
    try:
        return files.usages(file_id)
    except Exception:
        log.exception("usage provider failed for file %s", file_id)
        return None


def source_group(row: dict) -> str:
    if row.get("origin") == "upload":
        return "upload"
    source = (row.get("source_type") or "").lower()
    if source.startswith("avatar"):
        return "avatar"
    if "export" in source:
        return "export"
    if source.startswith("editor") or row.get("origin") == "derived":
        return "editor"
    return "generation"


def item(row: dict, *, with_usages: bool = False) -> dict:
    """A file as the library screen shows it."""
    out = files.public(row)
    used = safe_usages(row["id"])
    state = ingest_state(row) or {}
    out.update(
        ext=row.get("ext"),
        source_group=row.get("source_group") or source_group(row),
        usage_count=None if used is None else len(used),
        ingest={k: state.get(k) for k in ("status", "error_code", "error", "at")} if state else None,
    )
    if with_usages:
        out["usages"] = used
    return out


def list_files(*, kind: str | None = None, source: str | None = None, q: str | None = None,
               date_from: str | None = None, date_to: str | None = None, page: int = 1,
               limit: int = PAGE_SIZE) -> dict:
    """One page of library files, newest first. ``date_to`` is exclusive."""
    kinds = _split(kind, LIBRARY_KINDS, "kind") or list(LIBRARY_KINDS)
    sources = _split(source, SOURCE_GROUPS, "source")
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    page = max(1, int(page))
    where = ["is_service = 0", f"kind IN ({', '.join('?' * len(kinds))})"]
    params: list[Any] = list(kinds)
    if sources:
        where.append(f"({SOURCE_SQL}) IN ({', '.join('?' * len(sources))})")
        params.extend(sources)
    text = (q or "").strip()
    if text:
        where.append("(title LIKE ? ESCAPE '\\' OR original_name LIKE ? ESCAPE '\\')")
        params.extend([_like(text), _like(text)])
    start = normalize_ts(date_from, "date_from")
    end = normalize_ts(date_to, "date_to")
    if start:
        where.append("created_at >= ?")
        params.append(start)
    if end:
        where.append("created_at < ?")
        params.append(end)
    clause = " AND ".join(where)
    total = int(db.fetch_value(f"SELECT COUNT(*) FROM files WHERE {clause}", params, 0))
    rows = db.fetch_all(
        f"SELECT *, {SOURCE_SQL} AS source_group FROM files WHERE {clause} "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, (page - 1) * limit])
    return {"items": [item(r) for r in rows], "total": total, "page": page, "limit": limit,
            "pages": max(1, -(-total // limit))}


def get_library_row(file_id: int) -> dict:
    """A file the person may see and change here: anything that is not a service file."""
    row = files.get(file_id)
    if row.get("is_service"):
        raise NotFound("file", id=file_id)
    return row


def rename(file_id: int, title: str | None) -> dict:
    get_library_row(file_id)
    if title is not None and len(title.strip()) > MAX_TITLE:
        raise AppError("bad_request", 400, f"the name is longer than {MAX_TITLE} characters")
    return item(files.update(file_id, {"title": clean_title(title)}), with_usages=True)


def delete_many(ids: list[int]) -> dict:
    """Delete files that are not used anywhere; used ones are reported, never forced."""
    deleted: list[int] = []
    blocked: list[dict] = []
    missing: list[int] = []
    for file_id in dict.fromkeys(ids):
        row = db.get("files", file_id)
        if row is None or row.get("is_service"):
            missing.append(file_id)
            continue
        title = row.get("title") or row.get("original_name")
        try:
            files.delete(file_id)
        except AppError as exc:
            if exc.code != "file_in_use":
                raise
            blocked.append({"id": file_id, "title": title, "usages": exc.details.get("usages") or []})
            continue
        except Exception:
            # A module could not say whether it uses the file: keep the file.
            log.exception("usage check failed for file %s", file_id)
            blocked.append({"id": file_id, "title": title, "usages": None})
            continue
        deleted.append(file_id)
    return {"deleted": deleted, "blocked": blocked, "missing": missing}


def _tree_bytes(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def stats() -> dict:
    """Space taken by the library (by kind), by service files and the cache, and the
    free space on the disk that holds the data folder (Docker's disk)."""
    by_kind = {k: {"count": 0, "bytes": 0} for k in (*LIBRARY_KINDS, "other")}
    for r in db.fetch_all("SELECT kind, COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM files "
                          "WHERE is_service = 0 GROUP BY kind"):
        slot = by_kind[r["kind"] if r["kind"] in LIBRARY_KINDS else "other"]
        slot["count"] += int(r["n"])
        slot["bytes"] += int(r["b"])
    rows_bytes = int(db.fetch_value("SELECT COALESCE(SUM(size_bytes), 0) FROM files", (), 0))
    service_rows = int(db.fetch_value("SELECT COALESCE(SUM(size_bytes), 0) FROM files WHERE is_service = 1",
                                      (), 0))
    root = files.data_dir()
    files_bytes = _tree_bytes(root / "files")
    cache_bytes = _tree_bytes(root / "cache")
    # Posters, hover previews and leftovers sit in files/ without a size in the table.
    extra = max(0, files_bytes - rows_bytes)
    library_bytes = sum(v["bytes"] for v in by_kind.values())
    try:
        disk = shutil.disk_usage(root)
        disk_info = {"total": disk.total, "used": disk.used, "free": disk.free}
    except OSError:
        disk_info = None
    return {
        "by_kind": by_kind,
        "library_bytes": library_bytes,
        "service_bytes": service_rows + extra,
        "cache_bytes": cache_bytes,
        "total_bytes": library_bytes + service_rows + extra + cache_bytes,
        "disk": disk_info,
    }
