"""Storyboard: one sheet of panels drawn by an image model before the video is shot.

The editable part is the "shot" text (by default the brief). The technical
wrapper (the library layer ``video_storyboard_take``: grid, timecodes, lettering,
cast) is added on every press, and the full text is shown before pressing. The
pictures of the cast (opening frame, closing frame, references) go with it,
each labelled "Subject N".

A sheet can also be the user's own picture. While a sheet is attached it travels
with the take as a reference and the take prompt gets the
``video_storyboard_reference`` note (see ``runs.prompt_for_take``).
"""

from __future__ import annotations

import logging

from vf.core import db, files, google, models_registry, pricing, prompts
from vf.core.errors import AppError
from vf.modules.video import catalog, runs

log = logging.getLogger("vf.video")

TAKE_LAYER = "video_storyboard_take"
PURPOSE = "video_storyboard"
MIN_PANELS = 2
MAX_PANELS = 12
PREFERRED_SIZE = "2K"

_busy: set[int] = set()


def auto_panels(seconds: int | float | None) -> int:
    """About one panel per two seconds, 3 to 8."""
    return max(3, min(8, round(float(seconds or 8) / 2)))


def _panels(value: int | None, seconds: int | float | None) -> tuple[int, bool]:
    if not value:
        return auto_panels(seconds), True
    return max(MIN_PANELS, min(MAX_PANELS, int(value))), False


def _timecode(s: int) -> str:
    return f"{s // 60}:{s % 60:02d}"


def timecodes(seconds: int, panels: int) -> str:
    edges = [round(i * seconds / panels) for i in range(panels + 1)]
    return ", ".join(f"{i + 1:02d} {_timecode(edges[i])}–{_timecode(edges[i + 1])}" for i in range(panels))


def _image_model(model_id: str | None) -> dict:
    return models_registry.resolve("image", model_id)


def _image_size(m: dict) -> str:
    allowed = (m.get("caps") or {}).get("allowed_resolutions") or ["1K"]
    return PREFERRED_SIZE if PREFERRED_SIZE in allowed else allowed[0]


def cast_ids(run: dict) -> list[int]:
    """The pictures of what the film is of: opening frame, closing frame, references."""
    out: list[int] = []
    for fid in [run.get("first_frame_id"), run.get("last_frame_id"), *runs.reference_ids(run)]:
        if fid and int(fid) not in out and runs.file_row(fid) is not None:
            out.append(int(fid))
    return out


def _shot(run: dict, shot: str | None) -> tuple[str, str]:
    default = (run.get("brief") or "").strip()
    stored = (runs.storyboard(run).get("shot") or "").strip()
    text = (shot if shot is not None else (stored or default)).replace("\r\n", "\n").strip()
    if len(text) > runs.MAX_BRIEF:
        raise AppError("video_text_too_long", 400, "The text is too long", max=runs.MAX_BRIEF)
    return text, default


def _plan(run: dict, *, shot: str | None, panels: int | None, model_id: str | None) -> dict:
    m = _image_model(model_id)
    text, default = _shot(run, shot)
    seconds = int(run.get("duration") or runs.DEFAULT_SECONDS)
    aspect = run.get("aspect") or "16:9"
    count, auto = _panels(panels, seconds)
    cols, rows = catalog.storyboard_grid(count, aspect)
    cast = cast_ids(run)
    _code, language = catalog.language()
    values = {
        "seconds": seconds, "aspect": aspect, "panels": count, "cols": cols, "rows": rows, "language": language,
        "timecodes": timecodes(seconds, count), "shot": text, "camera": catalog.clip_phrase(run.get("camera_move")),
        "cast": ", ".join(f"Subject {i + 1}" for i in range(len(cast))), "look": "",
    }
    from vf.modules import library

    prompt = library.render_layer(TAKE_LAYER, values).strip() if text else ""
    max_refs = int((m.get("caps") or {}).get("max_references") or 0)
    size = _image_size(m)
    return {
        "model": m, "text": prompt, "shot": text, "default_shot": default, "panels": count, "auto_panels": auto,
        "cols": cols, "rows": rows, "sheet_aspect": catalog.sheet_aspect(cols, rows, aspect), "image_size": size,
        "cast": cast, "max_references": max_refs,
        "estimate_usd": pricing.estimate_image(m, image_size=size, input_images=len(cast), purpose=PURPOSE),
    }


def _refusal(plan: dict) -> AppError | None:
    if not plan["shot"]:
        return AppError("video_brief_empty", 400, "Describe the video first — the text is what gets filmed")
    if len(plan["cast"]) > plan["max_references"]:
        return AppError("video_too_many_references", 400, max=plan["max_references"], count=len(plan["cast"]),
                        model_id=plan["model"]["id"])
    return None


def preview(run_id: int, *, shot: str | None = None, panels: int | None = None,
            model_id: str | None = None) -> dict:
    """The full text that would go to the image model, its price, and why it cannot go (if so)."""
    run = runs.get_run(run_id)
    plan = _plan(run, shot=shot, panels=panels, model_id=model_id)
    refusal = _refusal(plan)
    return {
        "text": plan["text"], "shot": plan["shot"], "default_shot": plan["default_shot"], "panels": plan["panels"],
        "auto_panels": plan["auto_panels"], "min_panels": MIN_PANELS, "max_panels": MAX_PANELS,
        "cols": plan["cols"], "rows": plan["rows"], "sheet_aspect": plan["sheet_aspect"],
        "model_id": plan["model"]["id"], "image_size": plan["image_size"], "cast_count": len(plan["cast"]),
        "max_references": plan["max_references"], "estimate_usd": plan["estimate_usd"],
        "ready": refusal is None, "refusal": refusal.code if refusal else None,
        "refusal_details": refusal.details if refusal else {}, "current": runs.storyboard(run) or None,
    }


async def make(run_id: int, *, shot: str | None = None, panels: int | None = None,
               model_id: str | None = None) -> dict:
    """Draw the sheet (one paid picture). It is attached to the take at once (a visible toggle)."""
    run = runs.get_run(run_id)
    plan = _plan(run, shot=shot, panels=panels, model_id=model_id)
    refusal = _refusal(plan)
    if refusal is not None:
        raise refusal
    if run_id in _busy:
        raise AppError("video_storyboard_busy", 409, "The storyboard is being drawn")
    _busy.add(run_id)
    try:
        contents: list = []
        for i, fid in enumerate(plan["cast"]):
            contents += [f"Subject {i + 1}:", runs.image_blob(fid)]
        contents.append(plan["text"])
        m = plan["model"]
        result = await google.generate(
            purpose=PURPOSE, contents=contents, model_id=m["id"],
            prompt=google.PromptInfo(TAKE_LAYER, prompts.get(TAKE_LAYER).version), response="image",
            aspect_ratio=plan["sheet_aspect"], image_size=plan["image_size"], refs=[(runs.SOURCE, run_id)])
        if not result.images:
            raise AppError("video_storyboard_empty", 502, "The model answered without a picture")
        data, mime = result.images[0]
        title = (run.get("title") or "").strip() or runs.job_title(run)
        saved = files.save_bytes(data, mime=mime, name=f"storyboard-{run_id}.png", origin="generated",
                                 title=f"{title} · storyboard", source_type=runs.SOURCE, source_id=run_id,
                                 meta={"model_id": result.model_id, "panels": plan["panels"]})
    finally:
        _busy.discard(run_id)
    sb = {"file_id": saved["id"], "shot": plan["shot"], "prompt": plan["text"], "panels": plan["panels"],
          "auto_panels": plan["auto_panels"], "attached": True, "own": False, "model_id": result.model_id,
          "cost_usd": round(result.cost_usd or 0.0, 6), "made_at": db.now()}
    runs.update_run_state(run_id, storyboard_json=sb)
    runs.publish(run_id)
    return sb


def pick(run_id: int, file_id: int) -> dict:
    """Use the user's own picture as the sheet (free)."""
    run = runs.get_run(run_id)
    row = files.get(int(file_id))
    if row["kind"] != "image":
        raise AppError("video_frame_not_image", 400, "Pick a picture", file_id=file_id)
    old = runs.storyboard(run)
    sb = {"file_id": row["id"], "shot": old.get("shot"), "prompt": None, "panels": None, "attached": True,
          "own": True, "model_id": None, "cost_usd": 0.0, "made_at": db.now()}
    runs.update_run_state(run_id, storyboard_json=sb)
    runs.publish(run_id)
    return sb


def attach(run_id: int, attached: bool) -> dict:
    """Send the sheet with the take, or not."""
    run = runs.get_run(run_id)
    sb = runs.storyboard(run)
    if not sb.get("file_id"):
        raise AppError("video_storyboard_none", 409, "There is no storyboard yet")
    sb["attached"] = bool(attached)
    runs.update_run_state(run_id, storyboard_json=sb)
    runs.publish(run_id)
    return sb


def clear(run_id: int) -> None:
    """Forget the sheet (the picture stays in the media library)."""
    runs.get_run(run_id)
    runs.update_run_state(run_id, storyboard_json=None)
    runs.publish(run_id)


__all__ = ["attach", "auto_panels", "cast_ids", "clear", "make", "pick", "preview", "timecodes"]
