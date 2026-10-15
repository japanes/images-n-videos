"""Client of the ``render`` container (Node + ffmpeg).

Paths are relative to the shared data volume (``files/2026/10/x.mp4``).
Quick calls (probe, frame, match) answer at once; heavy ones (trim, concat,
compose, burn, mix, preview, split...) are queued there and polled here::

    result = await render.run("concat", {"inputs": [...], "output": rel}, ctx=job_ctx)
"""

from __future__ import annotations

import asyncio
from typing import Any

from vf.core.config import get_config
from vf.core.errors import AppError
from vf.core.services._http import call

POLL_SECONDS = 1.0


def _url(path: str) -> str:
    return get_config().render_url + path


async def health() -> dict:
    return await call("render", "GET", _url("/health"), timeout=5)


async def probe(rel: str) -> dict:
    return await call("render", "POST", _url("/probe"), json={"input": rel}, timeout=60)


async def frame(rel: str, output: str, at: float | str = "first", max_width: int | None = None) -> dict:
    body: dict[str, Any] = {"input": rel, "at": at, "output": output}
    if max_width:
        body["max_width"] = max_width
    return await call("render", "POST", _url("/frame"), json=body, timeout=120)


async def match(body: dict) -> dict:
    return await call("render", "POST", _url("/match"), json=body, timeout=300)


async def start(op: str, body: dict) -> str:
    answer = await call("render", "POST", _url(f"/{op}"), json=body, timeout=30)
    return answer["job_id"]


async def job(job_id: str) -> dict:
    return await call("render", "GET", _url(f"/jobs/{job_id}"), timeout=10)


async def cancel(job_id: str) -> None:
    try:
        await call("render", "DELETE", _url(f"/jobs/{job_id}"), timeout=10, ok_statuses=(404,))
    except AppError:
        pass


async def run(op: str, body: dict, *, ctx: Any = None, progress_from: float = 0.0,
              progress_to: float = 1.0, note: str | None = None) -> dict:
    """Start a queued render operation and wait for it. ``ctx`` is a ``jobs.JobContext``:
    its progress is updated and its cancel request stops the render too."""
    job_id = await start(op, body)
    try:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            if ctx is not None and ctx.cancelled:
                await cancel(job_id)
                ctx.raise_if_cancelled()
            state = await job(job_id)
            status = state.get("status")
            if ctx is not None and state.get("progress") is not None:
                ctx.progress(progress_from + (progress_to - progress_from) * float(state["progress"]), note)
            if status == "done":
                return state.get("result") or {}
            if status in ("error", "cancelled"):
                err = state.get("error") or {}
                raise AppError("render_failed", 502, err.get("message") or f"render {op} {status}",
                               op=op, service_code=err.get("code"), stderr_tail=err.get("stderr_tail"))
    except asyncio.CancelledError:
        await cancel(job_id)
        raise
