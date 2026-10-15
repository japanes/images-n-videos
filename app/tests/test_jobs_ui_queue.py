"""Module 13 "done when": group limits hold, and a restart loses nothing and does not pay twice."""

import asyncio

import pytest

from vf.core import db, jobs, settings


@pytest.fixture
async def runner(database):
    yield jobs.runner
    await jobs.runner.stop()
    jobs.runner.paused = None


async def _wait_all(ids, statuses=jobs.FINISHED, timeout=10.0):
    for _ in range(int(timeout / 0.02)):
        rows = [jobs.get(i) for i in ids]
        if all(r["status"] in statuses for r in rows):
            return rows
        await asyncio.sleep(0.02)
    raise AssertionError({i: jobs.get(i)["status"] for i in ids})


_load = {"now": 0, "peak": 0}


@jobs.handler("jobs_ui_test.frame", group="image")
async def _frame(ctx):
    _load["now"] += 1
    _load["peak"] = max(_load["peak"], _load["now"])
    try:
        await asyncio.sleep(0.05)
    finally:
        _load["now"] -= 1
    return {"n": ctx.payload["n"]}


_calls: list[dict] = []


@jobs.handler("jobs_ui_test.video", group="video", recover="retry")
async def _video(ctx):
    """Starts a paid operation once, then only polls it (the Veo pattern)."""
    if "operation" not in ctx.state:
        _calls.append({"job": ctx.id, "paid": True})
        ctx.save_state(operation=f"op-{ctx.id}")
    else:
        _calls.append({"job": ctx.id, "paid": False, "polled": ctx.state["operation"]})
    return {"operation": ctx.state["operation"]}


@jobs.handler("jobs_ui_test.once", group="text")
async def _once(ctx):
    return {"ok": True}


async def test_ten_frames_run_two_at_a_time(runner):
    _load.update(now=0, peak=0)
    await runner.start()
    ids = [jobs.enqueue("jobs_ui_test.frame", {"n": n}) for n in range(10)]
    rows = await _wait_all(ids)
    assert all(r["status"] == "done" for r in rows)
    assert _load["peak"] == 2
    assert [r["result_json"]["n"] for r in rows] == list(range(10))  # each frame got its own payload


async def test_group_limit_comes_from_settings(runner):
    _load.update(now=0, peak=0)
    settings.set("jobs.limit.image", 1)
    await runner.start()
    ids = [jobs.enqueue("jobs_ui_test.frame", {"n": n}) for n in range(4)]
    await _wait_all(ids)
    assert _load["peak"] == 1


async def test_restart_resumes_without_paying_twice(runner):
    _calls.clear()
    now = db.now()
    # What a restart leaves behind: rows still saying "running".
    started = db.insert("jobs", {"kind": "jobs_ui_test.video", "group_name": "video", "status": "running",
                                 "attempts": 1, "state_json": {"operation": "op-paid-before"},
                                 "created_at": now, "updated_at": now, "started_at": now})
    fresh = db.insert("jobs", {"kind": "jobs_ui_test.video", "group_name": "video", "status": "running",
                               "attempts": 1, "created_at": now, "updated_at": now, "started_at": now})
    plain = db.insert("jobs", {"kind": "jobs_ui_test.once", "group_name": "text", "status": "running",
                               "attempts": 1, "created_at": now, "updated_at": now, "started_at": now})
    waiting = db.insert("jobs", {"kind": "jobs_ui_test.once", "group_name": "text", "status": "queued",
                                 "attempts": 0, "created_at": now, "updated_at": now})
    await runner.start()
    rows = await _wait_all([started, fresh, plain, waiting])
    by_id = {r["id"]: r for r in rows}

    assert by_id[started]["status"] == "done"
    assert {"job": started, "paid": False, "polled": "op-paid-before"} in _calls
    assert by_id[fresh]["status"] == "done"
    assert [c for c in _calls if c["job"] == fresh] == [{"job": fresh, "paid": True}]
    # A handler without recover="retry" is never re-run on its own.
    assert by_id[plain]["status"] == "interrupted" and by_id[plain]["error_code"] == "interrupted"
    assert by_id[waiting]["status"] == "done"


async def test_manual_retry_keeps_saved_state(runner):
    _calls.clear()
    now = db.now()
    job_id = db.insert("jobs", {"kind": "jobs_ui_test.video", "group_name": "video", "status": "interrupted",
                                "attempts": 1, "state_json": {"operation": "op-1"}, "error_code": "stuck",
                                "created_at": now, "updated_at": now, "finished_at": now})
    await runner.start()
    jobs.retry(job_id)
    (row,) = await _wait_all([job_id])
    assert row["status"] == "done" and row["attempts"] == 2
    assert _calls == [{"job": job_id, "paid": False, "polled": "op-1"}]
