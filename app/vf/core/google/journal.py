"""The spend journal: one ``ai_calls`` row per Google call attempt.

A row is opened before the request (status ``running``) and closed after the
answer. Every attempt of a retry is a row of its own. The cost is computed
from the model's price at the moment of the call, and that price is copied
into the row so later price edits do not rewrite history.

Links to the things a call was made for (a work, a frame, an avatar, a video)
go to ``ai_call_refs``. A job can bind them once for everything inside it::

    with journal.bind_refs(("work", 3), ("frame", 12)):
        await gateway.generate(...)
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import time
from collections.abc import Iterable, Iterator
from typing import Any

from vf.core import db, events, pricing

STATUSES = ("running", "success", "error", "blocked", "cancelled")
RESPONSE_LIMIT = 20_000

Ref = tuple[str, int]

_bound_refs: contextvars.ContextVar[tuple[Ref, ...]] = contextvars.ContextVar("vf_ai_refs", default=())
_started: dict[int, float] = {}


@contextlib.contextmanager
def bind_refs(*refs: Ref) -> Iterator[None]:
    token = _bound_refs.set(_bound_refs.get() + tuple(refs))
    try:
        yield
    finally:
        _bound_refs.reset(token)


def bound_refs() -> tuple[Ref, ...]:
    return _bound_refs.get()


def _clip(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value if len(value) <= RESPONSE_LIMIT else value[:RESPONSE_LIMIT] + "…[truncated]"
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= RESPONSE_LIMIT:
        return value
    return {"truncated": True, "head": text[:RESPONSE_LIMIT]}


def start_call(*, kind: str, purpose: str, model: dict | None = None, model_id: str | None = None,
               region: str | None = None, role: str | None = None, prompt_code: str | None = None,
               prompt_version: int | None = None, prompt_text: str | None = None,
               request: dict | None = None, attachments: list[dict] | None = None, attempt: int = 1,
               refs: Iterable[Ref] = (), stub: bool = False, video_seconds: float | None = None,
               video_resolution: str | None = None, input_video_seconds: float | None = None) -> int:
    snapshot = None
    if model:
        snapshot = {"api": model.get("api"), "kind": model.get("kind"), "price": model.get("price") or {}}
    call_id = db.insert("ai_calls", {
        "created_at": db.now(),
        "attempt": attempt,
        "kind": kind,
        "purpose": purpose,
        "role": role,
        "model_id": (model or {}).get("id") or model_id,
        "region": region or (model or {}).get("region"),
        "price_snapshot_json": snapshot,
        "prompt_code": prompt_code,
        "prompt_version": prompt_version,
        "prompt_text": prompt_text,
        "request_json": request,
        "attachments_json": attachments,
        "video_seconds": video_seconds,
        "video_resolution": video_resolution,
        "input_video_seconds": input_video_seconds,
        "status": "running",
        "stub": stub,
    })
    _started[call_id] = time.monotonic()
    add_refs([call_id], [*bound_refs(), *refs])
    return call_id


def update_call(call_id: int, **values: Any) -> None:
    """Fill fields while the call is in flight (e.g. a video operation name)."""
    if values:
        db.update("ai_calls", call_id, values)


def finish_call(call_id: int, *, status: str, tokens_in: int | None = None, tokens_out: int | None = None,
                tokens_thinking: int | None = None, search_queries: int | None = None,
                search_requests: int | None = None, video_seconds: float | None = None,
                video_resolution: str | None = None, output_video_seconds: float | None = None,
                response: Any = None, error_code: str | None = None, error_text: str | None = None,
                http_status: int | None = None, operation_name: str | None = None,
                cost_usd: float | None = None) -> dict:
    """Close the row and compute its cost. Returns the finished row."""
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r}")
    row = db.get("ai_calls", call_id) or {}
    if cost_usd is None:
        snapshot = row.get("price_snapshot_json") or {}
        model = {"api": snapshot.get("api"), "price": snapshot.get("price") or {}}
        seconds = output_video_seconds if output_video_seconds is not None else video_seconds
        cost_usd = pricing.call_cost(
            model, tokens_in=tokens_in, tokens_out=tokens_out,
            search_requests=search_requests if search_requests is not None else search_queries,
            video_seconds=seconds if seconds is not None else row.get("video_seconds"),
            video_resolution=video_resolution or row.get("video_resolution"),
            blocked=status == "blocked",
        )
    started = _started.pop(call_id, None)
    values: dict[str, Any] = {
        "finished_at": db.now(),
        "duration_ms": int((time.monotonic() - started) * 1000) if started else None,
        "status": status,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thinking": tokens_thinking,
        "search_queries": search_queries,
        "response_json": _clip(response),
        "error_code": error_code,
        "error_text": error_text,
        "http_status": http_status,
        "cost_usd": round(float(cost_usd or 0), 6),
    }
    for key, value in (("video_seconds", video_seconds), ("video_resolution", video_resolution),
                       ("output_video_seconds", output_video_seconds), ("operation_name", operation_name)):
        if value is not None:
            values[key] = value
    db.update("ai_calls", call_id, values)
    finished = db.get("ai_calls", call_id) or {}
    events.publish("ai_call.finished", {
        "id": call_id,
        "kind": finished.get("kind"),
        "purpose": finished.get("purpose"),
        "model_id": finished.get("model_id"),
        "status": status,
        "cost_usd": finished.get("cost_usd"),
        "refs": [list(r) for r in refs_of(call_id)],
    })
    return finished


def add_refs(call_ids: Iterable[int], refs: Iterable[Ref]) -> None:
    refs = [(str(t), int(i)) for t, i in refs if t and i is not None]
    if not refs:
        return
    with db.tx():
        for call_id in call_ids:
            for ref_type, ref_id in refs:
                db.execute(
                    "INSERT OR IGNORE INTO ai_call_refs (call_id, ref_type, ref_id) VALUES (?, ?, ?)",
                    (call_id, ref_type, ref_id),
                )


def refs_of(call_id: int) -> list[Ref]:
    rows = db.fetch_all("SELECT ref_type, ref_id FROM ai_call_refs WHERE call_id = ? ORDER BY ref_type",
                        (call_id,))
    return [(r["ref_type"], r["ref_id"]) for r in rows]


def get_call(call_id: int) -> dict | None:
    row = db.get("ai_calls", call_id)
    if row:
        row["refs"] = [{"type": t, "id": i} for t, i in refs_of(call_id)]
    return row


def cost_of(ref_type: str, ref_id: int, *, include_stub: bool = True) -> float:
    """What everything linked to one object has cost so far."""
    sql = ("SELECT COALESCE(SUM(c.cost_usd), 0) FROM ai_calls c JOIN ai_call_refs r ON r.call_id = c.id "
           "WHERE r.ref_type = ? AND r.ref_id = ?")
    if not include_stub:
        sql += " AND c.stub = 0"
    return round(float(db.fetch_value(sql, (ref_type, ref_id), 0.0)), 6)


def spent_today() -> float:
    day = db.now()[:10]
    return round(float(db.fetch_value(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE created_at >= ? AND stub = 0",
        (f"{day}T00:00:00",), 0.0)), 6)


def recover() -> int:
    """After a restart nothing is in flight: close rows left ``running``.

    Rows with an ``operation_name`` are long Google operations (video) that the
    owning module resumes polling; it closes them itself (``resumable_calls``).
    """
    return db.execute(
        "UPDATE ai_calls SET status = 'error', error_code = 'interrupted', "
        "error_text = 'The app stopped while this call was in flight; Google may still have billed it.', "
        "finished_at = ? WHERE status = 'running' AND operation_name IS NULL",
        (db.now(),),
    ).rowcount


def resumable_calls(purpose: str | None = None) -> list[dict]:
    sql = "SELECT * FROM ai_calls WHERE status = 'running' AND operation_name IS NOT NULL"
    params: list = []
    if purpose:
        sql += " AND purpose = ?"
        params.append(purpose)
    return db.fetch_all(sql, params)


def resume_call(call_id: int) -> None:
    """Re-arm the duration clock for a call that is being polled again after a restart."""
    _started.setdefault(call_id, time.monotonic())
