"""HTTP routes of the shot ideas (/api/ideas/…). Contract: docs/dev/ideas-api.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from vf.core import jobs
from vf.core.errors import AppError
from vf.modules.ideas import cards, draw, estimate, scene, sets, write

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


def _body(body: dict[str, Any] | None) -> dict[str, Any]:
    if body is not None and not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    return dict(body or {})


# ── the setting (free) ──────────────────────────────────────────────────────

@router.get("/scene")
async def get_scene(roll: bool = False, seed: int | None = None) -> dict:
    """The axes and items of the setting; ``roll=true`` also throws the dice."""
    out: dict[str, Any] = {"axes": scene.vocabulary()}
    if roll:
        out["scene"] = scene.roll(seed)
    return out


# ── writing a set ───────────────────────────────────────────────────────────

@router.post("/estimate")
async def estimate_write(body: dict[str, Any] | None = None) -> dict:
    return estimate.write(_body(body))


@router.post("/sets")
async def start_set(body: dict[str, Any] | None = None) -> dict:
    return write.start(_body(body))


@router.get("/sets/{set_id}")
async def get_set(set_id: int) -> dict:
    return sets.get(set_id)


@router.post("/sets/{set_id}/cancel")
async def cancel_set(set_id: int) -> dict:
    row = sets.set_row(set_id)
    if row["status"] == "running" and row.get("job_id"):
        try:
            jobs.cancel(int(row["job_id"]))
        except AppError:
            pass
    return sets.get(set_id)


# ── the cards ───────────────────────────────────────────────────────────────

@router.patch("/sets/{set_id}/images/{n}")
async def edit_card(set_id: int, n: int, body: dict[str, Any] | None = None) -> dict:
    return cards.edit(set_id, n, _body(body))


@router.get("/sets/{set_id}/images/{n}/reroll/estimate")
async def reroll_estimate(set_id: int, n: int) -> dict:
    sets.image(sets.set_row(set_id), n)
    return estimate.reroll(set_id)


@router.post("/sets/{set_id}/images/{n}/reroll")
async def reroll_card(set_id: int, n: int) -> dict:
    return await cards.reroll(set_id, n)


@router.post("/sets/{set_id}/draw/estimate")
async def draw_estimate(set_id: int, body: dict[str, Any] | None = None) -> dict:
    return draw.estimate(set_id, _body(body).get("numbers", "all"))


@router.post("/sets/{set_id}/draw")
async def draw_cards(set_id: int, body: dict[str, Any] | None = None) -> dict:
    return draw.draw(set_id, _body(body).get("numbers", "all"))
