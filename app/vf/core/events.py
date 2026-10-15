"""In-process event bus feeding the browser over Server-Sent Events.

``publish`` may be called from any thread. Each SSE client gets its own queue;
slow clients drop events rather than block publishers (the UI re-fetches on
reconnect anyway).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger("vf.events")

_subscribers: set[asyncio.Queue] = set()
_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_closing = False
_CLOSE = object()  # queue item that ends a stream


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop, _closing
    _loop = loop
    _closing = False


def close_streams_soon() -> None:
    """``close_streams`` for a signal handler: the work runs on the event loop, so
    the handler never waits for a lock the interrupted code may hold."""
    global _closing
    _closing = True
    loop = _loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(close_streams)
    else:
        close_streams()


def close_streams() -> None:
    """End every open stream now (shutdown). An endless SSE response would otherwise
    hold the server for its whole graceful-shutdown timeout. Safe from any thread."""
    global _closing
    _closing = True
    with _lock:
        queues = list(_subscribers)
    loop = _loop
    for q in queues:
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(_close_queue, q)
        else:
            _close_queue(q)


def _close_queue(q: asyncio.Queue) -> None:
    while True:
        try:
            q.put_nowait(_CLOSE)
            return
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # a full queue must not keep the stream open
            except asyncio.QueueEmpty:
                pass


def publish(event_type: str, payload: dict[str, Any] | None = None) -> None:
    message = {"type": event_type, "data": payload or {}}
    with _lock:
        queues = list(_subscribers)
    if not queues:
        return
    loop = _loop
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    for q in queues:
        if running is not None and running is loop:
            _put(q, message)
        elif loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(_put, q, message)


def _put(q: asyncio.Queue, message: dict) -> None:
    try:
        q.put_nowait(message)
    except asyncio.QueueFull:
        pass


async def stream(heartbeat: float = 15.0) -> AsyncIterator[str]:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    with _lock:
        _subscribers.add(q)
    try:
        yield "retry: 3000\n\n"
        while not _closing:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if msg is _CLOSE:
                break
            # Unnamed SSE events carrying {"type", "data"}: the browser handles
            # every kind with one ``onmessage`` instead of a listener per type.
            data = json.dumps(msg, ensure_ascii=False, default=str)
            yield f"data: {data}\n\n"
    finally:
        with _lock:
            _subscribers.discard(q)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)
