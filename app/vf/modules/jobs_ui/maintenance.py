"""Housekeeping of background work: the minute loop and the daily loop.

Every minute:
- a row that says ``running`` while nothing in this process works on it (its task
  is gone) becomes ``interrupted`` — the page offers "retry". It is never re-run on
  its own: the work may have finished (and been paid for) before the bookkeeping
  broke, and a silent re-run could pay twice.
- a running job that has said nothing (no progress, no saved state) for longer than
  ``jobs.stuck_minutes`` is stopped and marked ``interrupted`` with the code
  ``stuck``. Generous by default; 0 turns it off. A handler that saved its Google
  operation name resumes polling on retry instead of paying again.

Once a day:
- a copy of the database into ``backups/daily-<UTC stamp>.db``; only the newest
  ``jobs.backup_keep`` of these are kept. The updater's own copies
  (``app-<version>-<stamp>.db``) are never touched here.
- finished jobs older than ``jobs.keep_days`` are deleted. Off by default (0 keeps
  them forever): other screens may still point at old jobs.

Frames and avatars stuck in their own tables, Veo polling and orphan files belong
to their modules (04, 09, 11, 10), which register their own scheduler hooks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vf.core import db, events, jobs, settings
from vf.core.config import get_config
from vf.core.scheduler import daily, every_minute

log = logging.getLogger("vf.jobs_ui")

settings.define("jobs.stuck_minutes", 180, group="jobs", kind="int", min=0, max=1440)
settings.define("jobs.keep_days", 0, group="jobs", kind="int", min=0, max=3650)
settings.define("jobs.backup_daily", True, group="jobs", kind="bool")
settings.define("jobs.backup_keep", 7, group="jobs", kind="int", min=1, max=60)

# A running row without a task gets this long before it is called orphaned.
ORPHAN_GRACE = timedelta(minutes=1)
# How long a stuck task gets to wind down after it is cancelled.
STOP_WAIT_SECONDS = 10.0

BACKUP_PREFIX = "daily-"
BACKUP_RE = re.compile(r"^daily-\d{8}T\d{6}Z\.db$")
PART_RE = re.compile(r"^daily-\d{8}T\d{6}Z\.db\.part$")


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _mark_interrupted(job_id: int, *, code: str, error: str | None = None) -> None:
    now = db.now()
    db.update("jobs", job_id, {"status": "interrupted", "error_code": code, "error": error,
                                "finished_at": now, "updated_at": now})
    row = db.get("jobs", job_id)
    if row:
        events.publish("job.updated", jobs.summary(row))


# ── every minute ────────────────────────────────────────────────────────────

@every_minute
async def release_stuck_jobs() -> dict:
    """Settle running rows that nothing works on, and stop jobs silent for too long."""
    out: dict[str, list[int]] = {"orphaned": [], "stuck": []}
    if not jobs.runner.alive():
        # Without the dispatch loop (tests, shutdown) "no task" proves nothing.
        return out
    now = datetime.now(UTC)
    grace_cutoff = _iso(now - ORPHAN_GRACE)
    stuck_minutes = int(settings.get("jobs.stuck_minutes") or 0)
    stuck_cutoff = _iso(now - timedelta(minutes=stuck_minutes)) if stuck_minutes > 0 else None

    to_stop: dict[int, asyncio.Task] = {}
    # No awaits between reading rows and looking at the runner's tasks: the runner
    # starts tasks on this same loop, so the picture cannot change underneath.
    rows = db.fetch_all("SELECT id, kind, updated_at, started_at FROM jobs WHERE status = 'running'")
    for row in rows:
        last = row.get("updated_at") or row.get("started_at") or ""
        task = jobs.runner.tasks.get(row["id"])
        if task is None:
            if last < grace_cutoff:
                _mark_interrupted(row["id"], code="interrupted")
                out["orphaned"].append(row["id"])
                log.warning("job %s (%s) was running with nothing behind it: marked interrupted",
                            row["id"], row["kind"])
        elif stuck_cutoff and last < stuck_cutoff:
            to_stop[row["id"]] = task

    if to_stop:
        for task in to_stop.values():
            task.cancel()
        await asyncio.wait(list(to_stop.values()), timeout=STOP_WAIT_SECONDS)
        for job_id in to_stop:
            _mark_interrupted(job_id, code="stuck",
                              error=f"No progress for more than {stuck_minutes} minutes; stopped.")
            out["stuck"].append(job_id)
            log.warning("job %s said nothing for over %d minutes: stopped", job_id, stuck_minutes)
    return out


# ── once a day ──────────────────────────────────────────────────────────────

def backup_files(folder: Path | None = None) -> list[Path]:
    """This module's daily copies, oldest first (the UTC stamp sorts by name)."""
    folder = folder or get_config().backups_dir
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and BACKUP_RE.match(p.name))


def make_backup(now: datetime | None = None) -> Path:
    """Copy the live database into ``backups/daily-<stamp>.db`` and check the copy."""
    folder = get_config().backups_dir
    folder.mkdir(parents=True, exist_ok=True)
    for leftover in folder.iterdir():
        if PART_RE.match(leftover.name):
            leftover.unlink(missing_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"{BACKUP_PREFIX}{stamp}.db"
    part = folder / f"{target.name}.part"
    try:
        db.instance().backup_to(part)
        conn = sqlite3.connect(str(part))
        try:
            # A self-contained file: no -wal/-shm companions needed to read it.
            conn.execute("PRAGMA journal_mode=DELETE")
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
        if check != "ok":
            raise RuntimeError(f"backup copy failed its check: {check}")
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return target


def rotate_backups(keep: int) -> list[str]:
    """Delete all but the newest ``keep`` daily copies. Returns the deleted names."""
    files = backup_files()
    keep = max(1, int(keep))
    removed = []
    for path in files[:-keep] if len(files) > keep else []:
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed


@daily
def daily_backup() -> dict:
    if not settings.get("jobs.backup_daily"):
        return {"skipped": True}
    target = make_backup()
    removed = rotate_backups(int(settings.get("jobs.backup_keep") or 7))
    log.info("daily backup %s (%d bytes), removed %d old", target.name, target.stat().st_size, len(removed))
    return {"file": target.name, "removed": removed}


@daily
def purge_old_jobs() -> int:
    """Delete finished jobs older than ``jobs.keep_days``. Active jobs are never touched."""
    days = int(settings.get("jobs.keep_days") or 0)
    if days <= 0:
        return 0
    cutoff = _iso(datetime.now(UTC) - timedelta(days=days))
    marks = ",".join("?" for _ in jobs.FINISHED)
    cur = db.execute(
        f"DELETE FROM jobs WHERE status IN ({marks}) AND COALESCE(finished_at, updated_at) < ?",
        (*jobs.FINISHED, cutoff),
    )
    if cur.rowcount:
        log.info("deleted %d finished jobs older than %d days", cur.rowcount, days)
    return cur.rowcount
