import asyncio

import pytest

from vf.core import db, jobs


@pytest.fixture
async def runner(database):
    await jobs.runner.start()
    yield jobs.runner
    await jobs.runner.stop()


async def _wait(job_id, statuses=jobs.FINISHED, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        row = jobs.get(job_id)
        if row["status"] in statuses:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} stuck in {jobs.get(job_id)['status']}")


@jobs.handler("test.echo", group="text")
async def _echo(ctx):
    ctx.progress(0.5, "half")
    return {"echo": ctx.payload.get("value")}


@jobs.handler("test.fail")
async def _fail(ctx):
    raise RuntimeError("boom")


@jobs.handler("test.slow", serial_key=lambda p: p.get("key"))
async def _slow(ctx):
    for _ in range(200):
        await asyncio.sleep(0.01)
        ctx.raise_if_cancelled()
    return {"done": True}


async def test_job_runs_to_done(runner):
    job_id = jobs.enqueue("test.echo", {"value": 5})
    row = await _wait(job_id)
    assert row["status"] == "done"
    assert row["result_json"] == {"echo": 5}


async def test_job_error_is_recorded(runner):
    row = await _wait(jobs.enqueue("test.fail"))
    assert row["status"] == "error" and "boom" in row["error"]


async def test_cancel_running_job(runner):
    job_id = jobs.enqueue("test.slow", {"key": "a"})
    await _wait(job_id, ("running",))
    jobs.cancel(job_id)
    assert (await _wait(job_id))["status"] == "cancelled"


async def test_serial_key_runs_one_at_a_time(runner):
    first = jobs.enqueue("test.slow", {"key": "same"})
    second = jobs.enqueue("test.slow", {"key": "same"})
    await _wait(first, ("running",))
    await asyncio.sleep(0.1)
    assert jobs.get(second)["status"] == "queued"
    jobs.cancel(first)
    jobs.cancel(second)


async def test_running_rows_are_interrupted_after_restart(database):
    job_id = db.insert("jobs", {"kind": "test.echo", "group_name": "text", "status": "running",
                                "created_at": db.now(), "updated_at": db.now()})
    jobs.runner.recover()
    assert jobs.get(job_id)["status"] == "interrupted"
