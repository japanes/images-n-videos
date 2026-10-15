"""Client-side pacing for Google calls: how many at once and how many per minute.

All calls draw on the same per-project quota, so one limiter is shared by the
whole app. Limits come from settings and change on the fly.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque

from vf.core import settings

settings.define("google.max_concurrency", 2, group="google", kind="int", min=1, max=16)
settings.define("google.max_rpm", 8, group="google", kind="int", min=1, max=600)
settings.define("google.timeout_seconds", 120, group="google", kind="int", min=10, max=900)
settings.define("google.max_attempts", 3, group="google", kind="int", min=1, max=6)
settings.define("google.video_wait_minutes", 45, group="google", kind="int", min=5, max=180)
settings.define("google.daily_cap_usd", 0.0, group="google", kind="float", min=0, max=1000)


class Limiter:
    def __init__(self):
        self._starts: deque[float] = deque()
        self._running = 0
        self._cond: asyncio.Condition | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _condition(self) -> asyncio.Condition:
        loop = asyncio.get_running_loop()
        if self._cond is None or self._loop is not loop:
            self._cond = asyncio.Condition()
            self._loop = loop
            self._running = 0
        return self._cond

    async def _acquire(self) -> None:
        cond = self._condition()
        async with cond:
            await cond.wait_for(lambda: self._running < int(settings.get("google.max_concurrency")))
            self._running += 1
        try:
            await self._pace()
        except BaseException:
            await self._release()
            raise

    async def _release(self) -> None:
        cond = self._condition()
        async with cond:
            self._running = max(0, self._running - 1)
            cond.notify_all()

    async def _pace(self) -> None:
        while True:
            now = time.monotonic()
            while self._starts and now - self._starts[0] >= 60.0:
                self._starts.popleft()
            if len(self._starts) < int(settings.get("google.max_rpm")):
                self._starts.append(now)
                return
            await asyncio.sleep(max(60.0 - (now - self._starts[0]), 0.05))

    @contextlib.asynccontextmanager
    async def slot(self):
        await self._acquire()
        try:
            yield
        finally:
            await self._release()

    def state(self) -> dict:
        now = time.monotonic()
        return {
            "running": self._running,
            "started_last_minute": sum(1 for t in self._starts if now - t < 60.0),
            "max_concurrency": int(settings.get("google.max_concurrency")),
            "max_rpm": int(settings.get("google.max_rpm")),
        }


limiter = Limiter()
