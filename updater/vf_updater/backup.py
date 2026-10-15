"""SQLite backups of /data/app.db before an update, with rotation and restore."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone

KEEP_BACKUPS = 5
_NAME_RE = re.compile(r"^app-.+-\d{8}T\d{6}Z\.db$")


def _safe_version(version: str) -> str:
    return re.sub(r"[^0-9A-Za-z.-]", "_", version or "unknown")


def create(db_path: str, backups_dir: str, from_version: str, now=None):
    """Copy the live database with the SQLite backup API. Returns the file path or None."""
    if not os.path.exists(db_path):
        return None
    os.makedirs(backups_dir, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    target = os.path.join(backups_dir, f"app-{_safe_version(from_version)}-{stamp}.db")
    tmp_target = target + ".part"
    if os.path.exists(tmp_target):
        os.unlink(tmp_target)
    src = sqlite3.connect(db_path, timeout=30)
    try:
        dst = sqlite3.connect(tmp_target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            check = dst.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise RuntimeError(f"backup integrity check failed: {check}")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    with open(tmp_target, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp_target, target)
    return target


def list_backups(backups_dir: str) -> list:
    """Backup files made by the updater, newest first."""
    try:
        names = [n for n in os.listdir(backups_dir) if _NAME_RE.match(n)]
    except OSError:
        return []
    paths = [os.path.join(backups_dir, n) for n in names]
    paths.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
    return paths


def rotate(backups_dir: str, keep: int = KEEP_BACKUPS, protect=()) -> list:
    """Delete old backups, keeping the newest `keep` and anything in `protect`."""
    removed = []
    protect = {os.path.abspath(p) for p in protect if p}
    for path in list_backups(backups_dir)[keep:]:
        if os.path.abspath(path) in protect:
            continue
        try:
            os.unlink(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def restore(backup_path: str, db_path: str) -> None:
    """Overwrite db_path with the backup. The app must be stopped."""
    if not backup_path or not os.path.exists(backup_path):
        raise FileNotFoundError(f"backup not found: {backup_path}")
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(db_path, timeout=30)
        try:
            src.backup(dst)
            dst.commit()
            try:
                dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.DatabaseError:
                pass
        finally:
            dst.close()
    finally:
        src.close()
