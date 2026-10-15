"""Daily cleanup of service leftovers.

Removes only:
- service files (``is_service = 1``) older than ``media.cleanup_service_hours``
  that no module uses;
- anything in ``cache/tmp`` older than that (upload spools, scratch files);
- posters and hover previews (``*.poster.jpg`` / ``*.preview.webp``) whose video
  is gone, older than that;
- thumbnail folders ``cache/thumbs/<id>`` of files that no longer exist.

Files of the person (``is_service = 0``: uploads, results) are never touched.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vf.core import db, files, scheduler, settings
from vf.core.errors import AppError

log = logging.getLogger("vf.media.cleanup")

DERIVED_SUFFIXES = (".poster.jpg", ".preview.webp")

settings.define("media.cleanup_service_hours", 24, group="media", kind="int", min=1, max=720)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _service_files(cutoff: str) -> tuple[int, int]:
    removed = kept = 0
    for row in db.fetch_all("SELECT id FROM files WHERE is_service = 1 AND created_at < ? ORDER BY id",
                            (cutoff,)):
        file_id = row["id"]
        try:
            if files.usages(file_id):
                kept += 1
                continue
            # Re-check the flag right before deleting: never a file of the person.
            current = db.get("files", file_id)
            if current is None or not current.get("is_service"):
                continue
            files.delete(file_id)
            removed += 1
        except AppError as exc:
            if exc.code == "file_in_use":
                kept += 1
            else:
                log.warning("cleanup: file %s skipped: %s", file_id, exc.message)
        except Exception:
            log.exception("cleanup: file %s skipped", file_id)
    return removed, kept


def _old(path: Path, cutoff_ts: float) -> bool:
    try:
        return path.lstat().st_mtime < cutoff_ts
    except OSError:
        return False


def _cache_tmp(root: Path, cutoff_ts: float) -> int:
    tmp = root / "cache" / "tmp"
    if not tmp.is_dir():
        return 0
    removed = 0
    for dirpath, dirnames, names in os.walk(tmp, topdown=False):
        for name in names:
            p = Path(dirpath) / name
            if _old(p, cutoff_ts):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        for name in dirnames:
            d = Path(dirpath) / name
            if d.is_symlink():
                if _old(d, cutoff_ts):
                    d.unlink(missing_ok=True)
                continue
            try:
                if _old(d, cutoff_ts) and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    return removed


def _orphan_derived(root: Path, cutoff_ts: float) -> int:
    base = root / "files"
    if not base.is_dir():
        return 0
    referenced: set[str] = set()
    stems: set[str] = set()
    for r in db.fetch_all("SELECT path, poster_path, preview_path FROM files"):
        for key in ("path", "poster_path", "preview_path"):
            if r.get(key):
                referenced.add(r[key])
        stems.add(r["path"].rsplit(".", 1)[0])
    removed = 0
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            suffix = next((s for s in DERIVED_SUFFIXES if name.endswith(s)), None)
            if suffix is None:
                continue
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            stem = rel[: -len(suffix)]
            if rel in referenced or stem in stems or not _old(p, cutoff_ts):
                continue
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _orphan_thumbs(root: Path) -> int:
    thumbs = root / "cache" / "thumbs"
    if not thumbs.is_dir():
        return 0
    ids = {int(r["id"]) for r in db.fetch_all("SELECT id FROM files")}
    removed = 0
    for d in thumbs.iterdir():
        if d.is_dir() and not d.is_symlink() and d.name.isdigit() and int(d.name) not in ids:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def run_cleanup(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    hours = int(settings.get("media.cleanup_service_hours"))
    cutoff = now - timedelta(hours=hours)
    cutoff_ts = cutoff.timestamp()
    root = files.data_dir()
    service_removed, service_kept = _service_files(_stamp(cutoff))
    report = {
        "service_files": service_removed,
        "service_files_in_use": service_kept,
        "tmp_files": _cache_tmp(root, cutoff_ts),
        "orphan_previews": _orphan_derived(root, cutoff_ts),
        "orphan_thumbs": _orphan_thumbs(root),
    }
    log.info("media cleanup: %s", report)
    return report


@scheduler.daily
def daily_cleanup() -> None:
    run_cleanup()
