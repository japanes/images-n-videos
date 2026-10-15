"""Housekeeping: orphaned and stuck jobs, daily backup with rotation, old job purge."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from vf.core import db, jobs, settings
from vf.core.config import get_config
from vf.modules.jobs_ui import maintenance


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()
    jobs.runner.paused = None


def _ago(**delta) -> str:
    moment = datetime.now(UTC) - timedelta(**delta)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def _wait(job_id, statuses, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        row = jobs.get(job_id)
        if row["status"] in statuses:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {jobs.get(job_id)['status']}")


def _running_row(updated_at: str) -> int:
    return db.insert("jobs", {"kind": "jobs_ui_test.ghost", "group_name": "image", "status": "running",
                              "attempts": 1, "created_at": updated_at, "started_at": updated_at,
                              "updated_at": updated_at})


@jobs.handler("jobs_ui_test.silent", group="text")
async def _silent(ctx):
    await asyncio.sleep(30)
    return {"never": True}


# ── orphaned and stuck ──────────────────────────────────────────────────────

async def test_orphaned_running_row_becomes_interrupted(runner):
    old = _running_row(_ago(minutes=5))
    fresh = _running_row(_ago(seconds=5))
    out = await maintenance.release_stuck_jobs()
    assert out == {"orphaned": [old], "stuck": []}
    row = jobs.get(old)
    assert row["status"] == "interrupted" and row["error_code"] == "interrupted" and row["finished_at"]
    assert jobs.get(fresh)["status"] == "running"  # still inside the grace period


async def test_nothing_is_released_without_the_dispatch_loop(database):
    old = _running_row(_ago(hours=5))
    assert await maintenance.release_stuck_jobs() == {"orphaned": [], "stuck": []}
    assert jobs.get(old)["status"] == "running"


async def test_silent_job_is_stopped_after_the_limit(runner):
    settings.set("jobs.stuck_minutes", 30)
    job_id = jobs.enqueue("jobs_ui_test.silent")
    await _wait(job_id, ("running",))
    assert await maintenance.release_stuck_jobs() == {"orphaned": [], "stuck": []}  # live and recent

    db.update("jobs", job_id, {"updated_at": _ago(minutes=31)})
    out = await maintenance.release_stuck_jobs()
    assert out == {"orphaned": [], "stuck": [job_id]}
    row = jobs.get(job_id)
    assert row["status"] == "interrupted" and row["error_code"] == "stuck"
    assert "30 minutes" in row["error"]
    assert job_id not in runner.tasks


async def test_stuck_check_can_be_turned_off(runner):
    settings.set("jobs.stuck_minutes", 0)
    job_id = jobs.enqueue("jobs_ui_test.silent")
    await _wait(job_id, ("running",))
    db.update("jobs", job_id, {"updated_at": _ago(days=3)})
    assert await maintenance.release_stuck_jobs() == {"orphaned": [], "stuck": []}
    assert jobs.get(job_id)["status"] == "running"
    jobs.cancel(job_id)
    await _wait(job_id, ("cancelled",))


async def test_stop_settles_a_running_row_nobody_works_on(runner):
    ghost = _running_row(_ago(seconds=1))
    assert jobs.cancel(ghost)["status"] == "cancelled"
    assert jobs.retry(ghost)["status"] == "queued"


# ── daily backup ────────────────────────────────────────────────────────────

def test_backup_is_a_checked_standalone_copy(database):
    db.insert("jobs", {"kind": "jobs_ui_test.mark", "group_name": "text", "status": "done",
                       "created_at": db.now(), "updated_at": db.now(), "title": "kept in copy"})
    path = maintenance.make_backup()
    assert maintenance.BACKUP_RE.match(path.name)
    assert not list(path.parent.glob("*.part"))
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("SELECT title FROM jobs WHERE kind = 'jobs_ui_test.mark'").fetchone()[0] == "kept in copy"
    finally:
        conn.close()


def test_rotation_keeps_newest_and_leaves_other_files(database):
    folder = get_config().backups_dir
    folder.mkdir(parents=True, exist_ok=True)
    updater_copy = folder / "app-1.0.0-20260101T000000Z.db"
    updater_copy.write_bytes(b"x")
    stray = folder / "notes.txt"
    stray.write_text("mine")
    (folder / "daily-20260101T000000Z.db.part").write_bytes(b"half")
    base = datetime(2026, 3, 1, 3, 0, tzinfo=UTC)
    made = [maintenance.make_backup(now=base + timedelta(days=i)).name for i in range(5)]
    assert not (folder / "daily-20260101T000000Z.db.part").exists()

    assert maintenance.rotate_backups(3) == made[:2]
    assert [p.name for p in maintenance.backup_files()] == made[2:]
    assert updater_copy.exists() and stray.exists()


def test_daily_backup_follows_settings(database):
    settings.set("jobs.backup_daily", False)
    assert maintenance.daily_backup() == {"skipped": True}
    assert maintenance.backup_files() == []
    settings.set("jobs.backup_daily", True)
    settings.set("jobs.backup_keep", 1)
    first = maintenance.daily_backup()
    assert first["removed"] == []
    folder = get_config().backups_dir
    (folder / first["file"]).rename(folder / "daily-20200101T000000Z.db")
    second = maintenance.daily_backup()
    assert second["removed"] == ["daily-20200101T000000Z.db"]
    assert [p.name for p in maintenance.backup_files()] == [second["file"]]


# ── purge ───────────────────────────────────────────────────────────────────

def test_purge_deletes_only_old_finished_jobs(database):
    assert maintenance.purge_old_jobs() == 0  # off by default
    settings.set("jobs.keep_days", 90)

    def row(status, finished):
        values = {"kind": "jobs_ui_test.old", "group_name": "text", "status": status,
                  "created_at": finished, "updated_at": finished}
        if status in jobs.FINISHED:
            values["finished_at"] = finished
        return db.insert("jobs", values)

    old_done = row("done", _ago(days=120))
    old_error = row("error", _ago(days=100))
    recent = row("done", _ago(days=10))
    old_queued = row("queued", _ago(days=200))
    assert maintenance.purge_old_jobs() == 2
    left = {r["id"] for r in db.fetch_all("SELECT id FROM jobs")}
    assert old_done not in left and old_error not in left
    assert {recent, old_queued} <= left

    settings.set("jobs.keep_days", 0)
    assert maintenance.purge_old_jobs() == 0
