"""HTTP routes of «Text on image» (/api/text/…). Contract: docs/dev/text-api.md."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from vf.core.errors import AppError
from vf.modules.text import backgrounds, designs, estimate, font_sheet, google_fonts, layouts, texts
from vf.modules.text import store as S

router = APIRouter(prefix="/api/text", tags=["text"])


def _body(body: dict[str, Any] | None) -> dict[str, Any]:
    if body is not None and not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    return dict(body or {})


# ── a design: open, look, change (free) ─────────────────────────────────────

@router.post("/designs/open")
async def open_design(body: dict[str, Any] | None = None) -> dict:
    return designs.open_design(_body(body))


@router.get("/designs/{design_id}")
async def get_design(design_id: int) -> dict:
    return designs.view(design_id)


@router.patch("/designs/{design_id}")
async def patch_design(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return designs.patch(design_id, _body(body))


@router.post("/designs/{design_id}/layout")
async def apply_layout(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return designs.apply_layout(design_id, _body(body).get("layout_id"))


@router.get("/designs/{design_id}/preview.png")
async def preview_png(design_id: int, max_side: int | None = None) -> Response:
    """The picture as «Save» draws it; ``X-Render-Report`` says what the renderer had to do."""
    png, report = await asyncio.to_thread(designs.render_png, design_id, max_side or 0)
    return Response(content=png, media_type="image/png",
                    headers={"X-Render-Report": designs.report_header(report), "Cache-Control": "no-store"})


@router.post("/designs/{design_id}/save")
async def save_design(design_id: int) -> dict:
    return await asyncio.to_thread(designs.save, design_id)


# ── paid steps (each one a journaled gateway call) ──────────────────────────

@router.post("/designs/{design_id}/place")
async def place(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return await designs.place(design_id, _body(body))


@router.post("/designs/{design_id}/write")
async def write(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return await texts.write(design_id, _body(body))


@router.post("/designs/{design_id}/variants")
async def variants(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return await texts.variants(design_id, _body(body))


@router.post("/designs/{design_id}/humanize")
async def humanize(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return await texts.humanize(design_id, _body(body))


@router.post("/designs/{design_id}/backgrounds")
async def start_backgrounds(design_id: int, body: dict[str, Any] | None = None) -> dict:
    return backgrounds.start(design_id, _body(body))


@router.post("/designs/{design_id}/backgrounds/cancel")
async def cancel_backgrounds(design_id: int) -> dict:
    S.design_row(design_id)
    return {"backgrounds": backgrounds.cancel(design_id)}


@router.post("/designs/{design_id}/backgrounds/{background_id}/use")
async def use_background(design_id: int, background_id: int) -> dict:
    return backgrounds.use(design_id, background_id)


@router.get("/estimate")
async def get_estimate(design_id: int | None = None, variants: int = 1, backgrounds: int = 1,
                       use_current: bool = False) -> dict:
    return estimate.estimate({"design_id": design_id, "variants": variants, "backgrounds": backgrounds,
                              "use_current": use_current})


# ── layouts ─────────────────────────────────────────────────────────────────

@router.get("/layouts")
async def list_layouts() -> dict:
    return {"items": layouts.list_layouts()}


@router.post("/layouts")
async def create_layout(body: dict[str, Any] | None = None) -> dict:
    return layouts.create(_body(body))


@router.delete("/layouts/{layout_id}")
async def delete_layout(layout_id: int) -> dict:
    layouts.delete(layout_id)
    return {"ok": True}


# ── fonts ───────────────────────────────────────────────────────────────────

@router.get("/fonts/google")
async def search_google_fonts(q: str | None = None, category: str | None = None, cyrillic: bool = False,
                              offset: int = 0, limit: int = 60) -> dict:
    return google_fonts.search(q, category=category or None, cyrillic=cyrillic, offset=offset, limit=limit)


@router.post("/fonts/google/add")
async def add_google_font(body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    return {"asset": await google_fonts.add_to_kit(body.get("kit_id"), body.get("family"))}


@router.get("/font-sheet")
async def get_font_sheet(kit_id: int, force: bool = False) -> dict:
    return await asyncio.to_thread(font_sheet.ensure_sheet, kit_id, force=force)
