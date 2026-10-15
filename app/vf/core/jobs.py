"""Background jobs: a table, per-group concurrency limits, serial keys, cancel,
recovery after a restart.

A module registers a handler::

    @jobs.handler("studio.frame", group="image")
    async def run_frame(ctx: jobs.JobContext) -> dict | None:
        ctx.progress(0.1)
        ...
        return {"file_id": 12}

and enqueues work with ``jobs.enqueue("studio.frame", {...}, ref_type="frame", ref_id=5)``.

Recovery after a restart (``recover``):
- ``"interrupt"`` (default): the job becomes ``interrupted``; the UI offers "retry".
- ``"retry"``: the job is queued again; ``ctx.state`` keeps what the handler saved
  with ``ctx.save_state`` (e.g. a Google operation name to resume polling instead
  of paying twice).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from vf.core import db, events, settings
from vf.core.errors import AppError, NotFound

log = logging.getLogger("vf.jobs")

ACTIVE = ("queued", "running")
FINISHED = ("done", "error", "cancelled", "interrupted")

STOP_TIMEOUT = 5.0  # seconds Runner.stop waits for cancelled jobs

GROUP_DEFAULTS = {"image": 2, "avatar": 2, "video": 2, "render": 2, "stt": 1, "text": 2, "default": 2}
for _group, _limit in GROUP_DEFAULTS.items():
    settings.define(f"jobs.limit.{_group}", _limit, group="jobs", kind="int", min=1, max=8)


class JobCancelled(Exception):
    """Raised inside a handler by ``ctx.raise_if_cancelled()``."""


@dataclass
class Handler:
    kind: str
    func: Callable[[JobContext], Awaitable[dict | None]]
    group: str
    serial_key: Callable[[dict], str | None] | None
    recover: str


_handlers: dict[str, Handler] = {}


def handler(kind: str, *, group: str = "default", serial_key: Callable[[dict], str | None] | None = None,
            recover: str = "interrupt"):
    if recover not in ("interrupt", "retry"):
        raise ValueError("recover must be 'interrupt' or 'retry'")

    def deco(func):
        _handlers[kind] = Handler(kind, func, group, serial_key, recover)
        return func

    return deco


def handlers() -> dict[str, Handler]:
    return dict(_handlers)


class JobContext:
    def __init__(self, row: dict):
        self.id: int = row["id"]
        self.kind: str = row["kind"]
        self.payload: dict = row.get("payload_json") or {}
        self.state: dict = row.get("state_json") or {}
        self.ref_type: str | None = row.get("ref_type")
        self.ref_id: int | None = row.get("ref_id")
        self.attempt: int = row.get("attempts") or 1
        self.cancel_requested = False
        self._last_progress = 0.0

    def progress(self, value: float | None, note: str | None = None, *, force: bool = False) -> None:
        now_ts = time.monotonic()
        if not force and now_ts - self._last_progress < 0.5 and value not in (0, 1):
            return
        self._last_progress = now_ts
        db.update("jobs", self.id, {"progress": value, "progress_note": note, "updated_at": db.now()})
        events.publish("job.progress", {"id": self.id, "kind": self.kind, "progress": value, "note": note,
                                        "ref_type": self.ref_type, "ref_id": self.ref_id})

    def save_state(self, **values: Any) -> None:
        self.state.update(values)
        db.update("jobs", self.id, {"state_json": self.state, "updated_at": db.now()})

    @property
    def cancelled(self) -> bool:
        return self.cancel_requested

    def raise_if_cancelled(self) -> None:
        if self.cancel_requested:
            raise JobCancelled()


# ── public API ──────────────────────────────────────────────────────────────

def enqueue(kind: str, payload: dict | None = None, *, ref_type: str | None = None, ref_id: int | None = None,
            title: str | None = None, priority: int = 0) -> int:
    if kind not in _handlers:
        raise AppError("unknown_job_kind", 500, kind=kind)
    h = _handlers[kind]
    payload = payload or {}
    job_id = db.insert("jobs", {
        "kind": kind, "group_name": h.group, "status": "queued", "payload_json": payload,
        "ref_type": ref_type, "ref_id": ref_id, "title": title, "priority": priority,
        "serial_key": h.serial_key(payload) if h.serial_key else None,
        "attempts": 0, "created_at": db.now(), "updated_at": db.now(),
    })
    _publish(job_id)
    runner.wake()
    return job_id


def get(job_id: int) -> dict:
    row = db.get("jobs", job_id)
    if row is None:
        raise NotFound("job")
    return row


def summary(row: dict) -> dict:
    return {k: row.get(k) for k in (
        "id", "kind", "group_name", "status", "progress", "progress_note", "title", "ref_type", "ref_id",
        "error_code", "error", "attempts", "created_at", "started_at", "finished_at", "result_json")}


def list_jobs(*, active_only: bool = False, limit: int = 100, ref_type: str | None = None,
              ref_id: int | None = None) -> list[dict]:
    where, params = [], []
    if active_only:
        where.append("status IN ('queued','running')")
    if ref_type:
        where.append("ref_type = ?")
        params.append(ref_type)
    if ref_id is not None:
        where.append("ref_id = ?")
        params.append(ref_id)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [summary(r) for r in db.fetch_all(sql, params)]


def cancel(job_id: int) -> dict:
    row = get(job_id)
    if row["status"] == "queued":
        _finish(job_id, "cancelled")
    elif row["status"] == "running":
        if job_id in runner.tasks:
            runner.cancel(job_id)
        else:
            # Nothing in this process is working on it (lost bookkeeping): there is no
            # task to stop, so "Stop" settles the row instead of doing nothing.
            _finish(job_id, "cancelled")
    return summary(get(job_id))


def retry(job_id: int) -> dict:
    row = get(job_id)
    if row["status"] not in ("error", "interrupted", "cancelled"):
        raise AppError("job_not_retryable", 409, status=row["status"])
    db.update("jobs", job_id, {"status": "queued", "error": None, "error_code": None, "progress": None,
                                "finished_at": None, "updated_at": db.now()})
    _publish(job_id)
    runner.wake()
    return summary(get(job_id))


def pause_new(reason: str = "update", *, ttl_seconds: float | None = None, target: str | None = None) -> None:
    """Hold new jobs; running ones go on. With ``ttl_seconds`` the pause lifts itself
    after that long, so an updater that died mid-update never leaves the app paused."""
    runner.paused = reason
    if ttl_seconds is not None:
        runner.paused_until = time.monotonic() + max(0.0, float(ttl_seconds))
    runner.paused_target = target
    events.publish("jobs.paused", {"reason": reason})


def resume_new() -> None:
    runner.paused = None
    events.publish("jobs.paused", {"reason": None})
    runner.wake()


def running_jobs() -> list[dict]:
    return [summary(r) for r in db.fetch_all("SELECT * FROM jobs WHERE status = 'running' ORDER BY id")]


# ── internals ───────────────────────────────────────────────────────────────

def _publish(job_id: int) -> None:
    row = db.get("jobs", job_id)
    if row:
        events.publish("job.updated", summary(row))


def _finish(job_id: int, status: str, *, result: dict | None = None, error: str | None = None,
            error_code: str | None = None) -> None:
    values: dict[str, Any] = {"status": status, "finished_at": db.now(), "updated_at": db.now()}
    if result is not None:
        values["result_json"] = result
    if status == "done":
        values["progress"] = 1
    values["error"] = error
    values["error_code"] = error_code
    db.update("jobs", job_id, values)
    _publish(job_id)


class Runner:
    def __init__(self):
        self.tasks: dict[int, asyncio.Task] = {}
        self.contexts: dict[int, JobContext] = {}
        self._paused: str | None = None
        self.paused_until: float | None = None  # time.monotonic() deadline of the pause
        self.paused_target: str | None = None  # version an update pause is for
        self._wake: asyncio.Event | None = None
        self._loop_task: asyncio.Task | None = None
        self._stopping = False

    @property
    def paused(self) -> str | None:
        """Why new jobs wait (e.g. "update"), or None. A pause past its deadline reads as None."""
        if self._paused and self.paused_until is not None and time.monotonic() >= self.paused_until:
            return None
        return self._paused

    @paused.setter
    def paused(self, value: str | None) -> None:
        self._paused = value
        self.paused_until = None
        self.paused_target = None

    def lift_expired_pause(self) -> bool:
        """End a pause whose deadline passed (tells the browser too). True if it did."""
        if not self._paused or self.paused is not None:
            return False
        log.warning("the %s pause was not lifted in time; new jobs run again", self._paused)
        resume_new()
        return True

    def alive(self) -> bool:
        """True while the dispatch loop runs in this process."""
        return self._loop_task is not None and not self._loop_task.done()

    def wake(self) -> None:
        if self._wake is None:
            return
        try:
            asyncio.get_running_loop()
            self._wake.set()
        except RuntimeError:
            loop = self._loop_task.get_loop() if self._loop_task else None
            if loop and not loop.is_closed():
                loop.call_soon_threadsafe(self._wake.set)

    async def start(self) -> None:
        self._stopping = False
        self._wake = asyncio.Event()
        self.recover()
        self._loop_task = asyncio.create_task(self._loop(), name="jobs-loop")

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        tasks = list(self.tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            # Bounded: Docker kills the container 30 s after SIGTERM, the database must close first.
            _done, stuck = await asyncio.wait(tasks, timeout=STOP_TIMEOUT)
            if stuck:
                log.warning("%d job(s) did not stop in %s s; leaving them", len(stuck), STOP_TIMEOUT)
        self.tasks.clear()
        self.contexts.clear()
        self._loop_task = None

    def recover(self) -> None:
        for row in db.fetch_all("SELECT * FROM jobs WHERE status = 'running'"):
            h = _handlers.get(row["kind"])
            if h and h.recover == "retry":
                db.update("jobs", row["id"], {"status": "queued", "updated_at": db.now()})
            else:
                db.update("jobs", row["id"], {"status": "interrupted", "finished_at": db.now(),
                                              "error_code": "interrupted", "updated_at": db.now()})

    def cancel(self, job_id: int) -> None:
        ctx = self.contexts.get(job_id)
        if ctx:
            ctx.cancel_requested = True
        task = self.tasks.get(job_id)
        if task:
            task.cancel()

    async def _loop(self) -> None:
        assert self._wake is not None
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                self.dispatch()
            except Exception:
                log.exception("job dispatch failed")

    def dispatch(self) -> None:
        self.lift_expired_pause()
        if self.paused:
            return
        running = db.fetch_all("SELECT id, group_name, serial_key FROM jobs WHERE status = 'running'")
        per_group: dict[str, int] = {}
        busy_keys = set()
        for r in running:
            per_group[r["group_name"]] = per_group.get(r["group_name"], 0) + 1
            if r["serial_key"]:
                busy_keys.add(r["serial_key"])
        queued = db.fetch_all("SELECT * FROM jobs WHERE status = 'queued' ORDER BY priority DESC, id")
        for row in queued:
            h = _handlers.get(row["kind"])
            if h is None:
                _finish(row["id"], "error", error=f"no handler for {row['kind']}", error_code="unknown_job_kind")
                continue
            limit = int(settings.get(f"jobs.limit.{h.group}", GROUP_DEFAULTS.get(h.group, 2)) or 1)
            if per_group.get(h.group, 0) >= limit:
                continue
            if row["serial_key"] and row["serial_key"] in busy_keys:
                continue
            per_group[h.group] = per_group.get(h.group, 0) + 1
            if row["serial_key"]:
                busy_keys.add(row["serial_key"])
            self._start(row, h)

    def _start(self, row: dict, h: Handler) -> None:
        attempts = (row.get("attempts") or 0) + 1
        db.update("jobs", row["id"], {"status": "running", "attempts": attempts, "started_at": db.now(),
                                       "updated_at": db.now(), "progress": None, "error": None,
                                       "error_code": None})
        row = db.get("jobs", row["id"]) or row
        ctx = JobContext(row)
        self.contexts[ctx.id] = ctx
        self.tasks[ctx.id] = asyncio.create_task(self._run(ctx, h), name=f"job-{ctx.id}")
        _publish(ctx.id)

    async def _run(self, ctx: JobContext, h: Handler) -> None:
        try:
            result = await h.func(ctx)
            if ctx.cancel_requested:
                _finish(ctx.id, "cancelled")
            else:
                _finish(ctx.id, "done", result=result if isinstance(result, dict) else None)
        except (asyncio.CancelledError, JobCancelled):
            if ctx.cancel_requested:
                _finish(ctx.id, "cancelled")
            elif self._stopping:
                # Shutdown: leave the row as "running"; recover() decides on next start.
                pass
            else:
                _finish(ctx.id, "cancelled")
        except AppError as exc:
            _finish(ctx.id, "error", error=exc.message, error_code=exc.code)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None) or "internal"
            text = getattr(exc, "raw", None) or str(exc) or exc.__class__.__name__
            if code == "internal":
                log.exception("job %s (%s) failed", ctx.id, ctx.kind)
            _finish(ctx.id, "error", error=str(text)[:4000], error_code=str(code))
        finally:
            self.tasks.pop(ctx.id, None)
            self.contexts.pop(ctx.id, None)
            self.wake()


runner = Runner()


def is_idle() -> bool:
    return not runner.tasks
