"""HTTP routes of the video module (/api/video/…). Contract: docs/dev/video-api.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from vf.core.errors import AppError
from vf.modules.video import brief, catalog, extend, generate, runs, storyboard, view

router = APIRouter(prefix="/api/video", tags=["video"])


def _body(body: dict[str, Any] | None) -> dict[str, Any]:
    return dict(body or {})


def _int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, field=name) from None


def _steps(body: dict[str, Any]) -> list[dict]:
    steps = body.get("steps")
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise AppError("bad_request", 400, field="steps")
    return [s if isinstance(s, dict) else {} for s in steps]


# ── catalogue ───────────────────────────────────────────────────────────────


@router.get("/models")
async def models() -> dict:
    return {"models": [catalog.model_info(m) for m in catalog.video_models()],
            "extension_models": [catalog.model_info(m) for m in catalog.extension_models()]}


@router.get("/camera-moves")
async def camera_moves() -> dict:
    return {"categories": catalog.camera_categories(), "moves": catalog.camera_moves()}


# ── runs ────────────────────────────────────────────────────────────────────


@router.get("/runs")
async def list_runs(limit: int = 50) -> dict:
    return {"items": [view.list_item(r) for r in runs.list_runs(max(1, min(int(limit), 200)))]}


@router.post("/runs")
async def create_run(body: dict[str, Any] | None = None) -> dict:
    run = runs.create_run(_body(body))
    return view.public_run(run["id"])


@router.get("/runs/{run_id}")
async def get_run(run_id: int) -> dict:
    return view.public_run(run_id)


@router.patch("/runs/{run_id}")
async def update_run(run_id: int, body: dict[str, Any] | None = None) -> dict:
    runs.update_run(run_id, _body(body))
    return view.public_run(run_id)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int) -> dict:
    runs.delete_run(run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/start")
async def start(run_id: int) -> dict:
    runs.start_take(run_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/stop")
async def stop(run_id: int) -> dict:
    runs.stop_run(run_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/versions/{number}/choose")
async def choose_version(run_id: int, number: int) -> dict:
    runs.choose_version(run_id, number)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/undo")
async def undo(run_id: int) -> dict:
    runs.undo_last(run_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/frame")
async def take_frame(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    at = body.get("at", "last")
    if not isinstance(at, str):
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise AppError("video_frame_at", 400, at=at) from None
    return await generate.take_frame(run_id, at, _int(body.get("version"), "version"))


# ── extension ───────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/extend")
async def extend_info(run_id: int, model_id: str | None = None) -> dict:
    return extend.info(run_id, model_id)


@router.post("/runs/{run_id}/extend/estimate")
async def extend_estimate(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    return extend.estimate(run_id, _steps(body), body.get("model_id"))


@router.post("/runs/{run_id}/extend")
async def extend_start(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    extend.start_extend(run_id, _steps(body), model_id=body.get("model_id"),
                        pause_each=bool(body.get("pause_each", True)))
    return view.public_run(run_id)


@router.post("/runs/{run_id}/extend/continue")
async def extend_continue(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    extend.continue_plan(run_id, _steps(body) if "steps" in body else None)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/extend/drop")
async def extend_drop(run_id: int) -> dict:
    extend.drop_plan(run_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/continue/estimate")
async def continue_estimate(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    return extend.continue_estimate(run_id, _int(body.get("seconds"), "seconds") or 0, body.get("model_id"))


@router.post("/runs/{run_id}/continue")
async def continue_start(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    extend.start_continue(run_id, str(body.get("text") or ""), _int(body.get("seconds"), "seconds") or 0,
                          model_id=body.get("model_id"))
    return view.public_run(run_id)


# ── «Write it for me» ───────────────────────────────────────────────────────


@router.get("/runs/{run_id}/brief/estimate")
async def brief_estimate(run_id: int, research: bool = True) -> dict:
    return brief.estimate_write(run_id, research=research)


@router.post("/runs/{run_id}/brief/write")
async def brief_write(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    result = await brief.write_brief(run_id, research=bool(body.get("research", True)),
                                     force=bool(body.get("force", False)))
    return {"result": result, "run": view.public_run(run_id)}


@router.post("/runs/{run_id}/brief/restore")
async def brief_restore(run_id: int) -> dict:
    brief.restore_previous(run_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/brief/camera")
async def brief_camera(run_id: int) -> dict:
    brief.apply_camera_suggestion(run_id)
    return view.public_run(run_id)


# ── storyboard ──────────────────────────────────────────────────────────────


@router.post("/runs/{run_id}/storyboard/preview")
async def storyboard_preview(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    return storyboard.preview(run_id, shot=body.get("shot"), panels=_int(body.get("panels"), "panels"),
                              model_id=body.get("model_id"))


@router.post("/runs/{run_id}/storyboard")
async def storyboard_make(run_id: int, body: dict[str, Any] | None = None) -> dict:
    body = _body(body)
    await storyboard.make(run_id, shot=body.get("shot"), panels=_int(body.get("panels"), "panels"),
                          model_id=body.get("model_id"))
    return view.public_run(run_id)


@router.post("/runs/{run_id}/storyboard/pick")
async def storyboard_pick(run_id: int, body: dict[str, Any] | None = None) -> dict:
    file_id = _int(_body(body).get("file_id"), "file_id")
    if not file_id:
        raise AppError("bad_request", 400, field="file_id")
    storyboard.pick(run_id, file_id)
    return view.public_run(run_id)


@router.post("/runs/{run_id}/storyboard/attach")
async def storyboard_attach(run_id: int, body: dict[str, Any] | None = None) -> dict:
    storyboard.attach(run_id, bool(_body(body).get("attached", True)))
    return view.public_run(run_id)


@router.delete("/runs/{run_id}/storyboard")
async def storyboard_clear(run_id: int) -> dict:
    storyboard.clear(run_id)
    return view.public_run(run_id)


__all__ = ["router"]
