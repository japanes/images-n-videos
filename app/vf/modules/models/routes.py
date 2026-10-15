"""HTTP API of the models screen on top of the core ``/api/models`` routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from vf.modules.models import service

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/overview")
async def get_overview() -> dict:
    """Effective model of each kind and when availability was last checked."""
    return service.overview()


@router.post("/check")
async def post_check() -> dict:
    """Free listing of Google's models; marks which ones the project can use."""
    result = await service.check_availability()
    return {**result, **service.overview()}


@router.delete("/check")
async def delete_check() -> dict:
    """Forget the availability marks (every model becomes "not checked")."""
    service.reset_availability()
    return service.overview()


class PriceBody(BaseModel):
    price: dict | None = None


@router.put("/{model_id}/price")
async def put_price(model_id: str, body: PriceBody) -> dict:
    """The user's own price (only money fields of the registry price); null resets it."""
    return service.set_price(model_id, body.price)
