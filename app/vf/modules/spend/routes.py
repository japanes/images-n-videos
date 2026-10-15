"""HTTP API of the spend screen: ``/api/spend/...`` (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from vf.modules.spend import service

router = APIRouter(prefix="/api/spend", tags=["spend"])


def call_filters(date_from: str | None = None, date_to: str | None = None, tz: int = 0, kind: str | None = None,
                 purpose: str | None = None, status: str | None = None, model_id: str | None = None,
                 include_stub: bool = False, ref_type: str | None = None,
                 ref_id: int | None = None) -> service.Filters:
    """Query string -> filters. Dates are the user's local days (inclusive), ``tz`` is minutes east of UTC.
    ``kind``/``purpose``/``status``/``model_id`` take one value or a comma list."""
    return service.Filters(
        date_from=service.parse_day(date_from, field="date_from"),
        date_to=service.parse_day(date_to, field="date_to"),
        tz=service.check_tz(tz),
        kind=service.split_list(kind),
        purpose=service.split_list(purpose),
        status=service.split_list(status),
        model_id=service.split_list(model_id),
        include_stub=include_stub,
        ref_type=ref_type or None,
        ref_id=ref_id,
    )


@router.get("/summary")
async def get_summary(tz: int = 0) -> dict:
    return service.summary(service.check_tz(tz))


@router.get("/stats")
async def get_stats(f: service.Filters = Depends(call_filters)) -> dict:
    return service.stats(f)


@router.get("/calls")
async def get_calls(f: service.Filters = Depends(call_filters), limit: int = Query(50, ge=1, le=500),
                    offset: int = Query(0, ge=0)) -> dict:
    return service.list_calls(f, limit=limit, offset=offset)


@router.get("/calls/{call_id}")
async def get_call(call_id: int) -> dict:
    return service.get_call(call_id)


@router.get("/filters")
async def get_filters() -> dict:
    return service.filter_choices()


@router.get("/cost")
async def get_cost(ref_type: str = Query(..., min_length=1, max_length=64), ref_id: int = Query(...)) -> dict:
    return service.cost_of(ref_type, ref_id)
