"""HTTP API of the jobs page. Cancel and retry are the core's ``/api/jobs/{id}/...``."""

from __future__ import annotations

from fastapi import APIRouter, Query

from vf.modules.jobs_ui import service

router = APIRouter(prefix="/api/jobs_ui", tags=["jobs_ui"])


@router.get("/list")
async def list_jobs(status: str = "all", group: str | None = None, kind: str | None = None,
                    ref_type: str | None = None, ref_id: int | None = None, q: str | None = None,
                    limit: int = Query(50, ge=1, le=200), before_id: int | None = None) -> dict:
    return service.list_page(status=status, group=group, kind=kind, ref_type=ref_type, ref_id=ref_id,
                             q=q, limit=limit, before_id=before_id)


@router.get("/overview")
async def overview() -> dict:
    return service.overview()


@router.get("/health")
async def health() -> dict:
    return await service.health()
