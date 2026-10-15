"""Periodic work: ``@every_minute`` and ``@daily`` hooks registered by modules."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from vf.core import db

log = logging.getLogger("vf.scheduler")

_minutely: list[Callable] = []
_daily: list[Callable] = []


def every_minute(func: Callable) -> Callable:
    _minutely.append(func)
    return func


def daily(func: Callable) -> Callable:
    _daily.append(func)
    return func


async def _call(func: Callable) -> None:
    try:
        if inspect.iscoroutinefunction(func):
            await func()
        else:
            await asyncio.to_thread(func)
    except Exception:
        log.exception("scheduled task %s failed", getattr(func, "__qualname__", func))


async def run_minutely() -> None:
    for func in list(_minutely):
        await _call(func)


async def run_daily(force: bool = False) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for func in list(_daily):
        name = f"{func.__module__}.{func.__qualname__}"
        last = db.fetch_value("SELECT last_run FROM scheduler_runs WHERE name = ?", (name,))
        if not force and last == today:
            continue
        await _call(func)
        db.execute(
            "INSERT INTO scheduler_runs (name, last_run) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET last_run = excluded.last_run",
            (name, today),
        )


class Scheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            await run_minutely()
            await run_daily()
            await asyncio.sleep(60)


scheduler = Scheduler()
