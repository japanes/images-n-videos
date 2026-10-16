"""«Write it for me»: one paragraph that is filmed as one take.

Two text calls, both journaled and priced before the button:

1. the market read (``video.research``, role ``research``, web search) — what the
   leaders of the niche shoot now. Cached by niche + platform for
   ``video.research_cache_days`` days, so the same niche is not paid twice;
2. the shot (``video.brief``, role ``video_brief``) from the niche, platform,
   length, shape, the text already in the box, the camera moves and the read,
   with the opening frame attached when there is one.

The answer replaces the text in the box; the old text is kept in
``brief_meta.replaced`` ("return the previous one"). The camera move the writer
suggests is stored, not applied: the user picks it with one click.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from vf.core import db, models_registry, pricing, prompts, settings
from vf.core.errors import AppError
from vf.core.google import GoogleCallError
from vf.modules.video import catalog, runs

log = logging.getLogger("vf.video")

RESEARCH_PROMPT = "video.research"
BRIEF_PROMPT = "video.brief"
RESEARCH_HEADING = "VIDEO RESEARCH — how this category is shooting and cutting video right now"
PHOTO_SIDE = 1024  # the opening frame goes to the writer at most this big

_busy: set[int] = set()


def _key(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def cache_days() -> int:
    try:
        return max(0, int(settings.get("video.research_cache_days") or 0))
    except (TypeError, ValueError):
        return 0


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def cached_research(niche: str | None, platform: str | None) -> dict | None:
    """The read of this niche + platform younger than the cache setting, or None."""
    days = cache_days()
    if days <= 0 or not _key(niche):
        return None
    cutoff = _stamp(datetime.now(UTC) - timedelta(days=days))
    return db.fetch_one("SELECT * FROM video_research WHERE niche_key = ? AND platform = ? AND created_at >= ?",
                        (_key(niche), _key(platform), cutoff))


def _research_block(niche: str, summary: str) -> str:
    return "\n".join([RESEARCH_HEADING, f"NICHE: {niche}", "", summary.strip()]).strip()


def _models() -> tuple[dict, dict]:
    return models_registry.model_for_role("research"), models_registry.model_for_role("video_brief")


def estimate_write(run_id: int, *, research: bool = True) -> dict:
    """Price of "Write it for me": the text and the read as two parts (the read is 0 when cached)."""
    run = runs.get_run(run_id)
    research_model, brief_model = _models()
    photo = 1 if runs.file_row(run.get("first_frame_id")) else 0
    niche = (run.get("niche") or "").strip()
    cached = cached_research(niche, run.get("platform")) if niche else None
    brief_usd = pricing.estimate_text(brief_model, purpose="video_brief", input_images=photo)
    research_usd = 0.0
    if research and niche and cached is None:
        research_usd = pricing.estimate_text(research_model, purpose="video_research", search=True)
    meta = run.get("brief_meta_json") or {}
    written_for = meta.get("seconds")
    return {
        "brief_usd": brief_usd, "research_usd": research_usd, "total_usd": round(brief_usd + research_usd, 4),
        "research": bool(research and niche), "research_cached": cached is not None,
        "research_cached_at": cached["created_at"] if cached else None, "niche_needed": research and not niche,
        "brief_exists": bool((run.get("brief") or "").strip()), "photo": bool(photo),
        "brief_model_id": brief_model["id"], "research_model_id": research_model["id"],
        "written_for_seconds": written_for,
        "duration_changed": bool(written_for and run.get("duration") and int(written_for) != int(run["duration"])),
        "can_restore": bool(meta.get("replaced")),
    }


async def _research(run: dict, niche: str) -> dict:
    """The read (from the cache or a paid search). A failed search does not stop the writing."""
    platform = (run.get("platform") or "").strip()
    cached = cached_research(niche, platform)
    if cached is not None:
        return {"block": _research_block(niche, cached["summary"]), "cached": True, "cost_usd": 0.0,
                "error_code": None}
    try:
        result = await prompts.run_prompt(
            RESEARCH_PROMPT, {"niche": niche, "platform": platform, "today": datetime.now(UTC).date().isoformat()},
            purpose="video_research", search=True, refs=[(runs.SOURCE, run["id"])])
    except GoogleCallError as err:
        log.warning("video research for run %s failed: %s", run["id"], err.code)
        return {"block": "", "cached": False, "cost_usd": 0.0, "error_code": err.code}
    summary = (result.text or "").strip()
    if not summary:
        return {"block": "", "cached": False, "cost_usd": result.cost_usd or 0.0, "error_code": "empty_answer"}
    now = db.now()
    db.execute(
        "INSERT INTO video_research (niche_key, platform, summary, model_id, cost_usd, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (niche_key, platform) DO UPDATE SET summary = excluded.summary, "
        "model_id = excluded.model_id, cost_usd = excluded.cost_usd, created_at = excluded.created_at",
        (_key(niche), _key(platform), summary, result.model_id, result.cost_usd or 0.0, now))
    return {"block": _research_block(niche, summary), "cached": False, "cost_usd": result.cost_usd or 0.0,
            "error_code": None}


def camera_menu() -> str:
    """The camera moves as the writer reads them: ``code — phrase`` one to a line."""
    lines = []
    for move in catalog.camera_moves():
        phrase = catalog.clip_phrase(move["code"]).strip()
        if phrase:
            lines.append(f"{move['code']} — {phrase}")
    return "\n".join(lines)


def inputs_block(run: dict, research_block: str = "") -> str:
    """What the writer is given besides the photograph (empty lines are left out)."""
    _code, language = catalog.language()
    lines = [("NICHE", (run.get("niche") or "").strip()), ("LANGUAGE", language),
             ("PLATFORM", (run.get("platform") or "").strip()),
             ("LENGTH", f"{run['duration']} seconds" if run.get("duration") else ""),
             ("ASPECT", run.get("aspect") or "")]
    concept = (run.get("brief") or "").strip()
    menu = camera_menu()
    sections = ["\n".join(f"{label}: {value}" for label, value in lines if value),
                f"CONCEPT:\n{concept}" if concept else "", f"CAMERA MOVES:\n{menu}" if menu else "",
                research_block]
    return "\n\n".join(s for s in sections if s.strip())


async def write_brief(run_id: int, *, research: bool = True, force: bool = False) -> dict:
    """Press "Write it for me". Refusals first; ``force`` replaces text already in the box."""
    run = runs.get_run(run_id)
    niche = (run.get("niche") or "").strip()
    first = run.get("first_frame_id") if runs.file_row(run.get("first_frame_id")) else None
    if research and not niche:
        raise AppError("video_niche_empty", 400, "Say what the video is about first")
    if not niche and not (run.get("brief") or "").strip() and not first:
        raise AppError("video_niche_empty", 400, "Say what the video is about first")
    if (run.get("brief") or "").strip() and not force:
        raise AppError("video_brief_exists", 409, "The box already has a text")
    if run_id in _busy:
        raise AppError("video_brief_busy", 409, "The text is being written")
    _busy.add(run_id)
    try:
        read = await _research(run, niche) if research else {"block": "", "cached": False, "cost_usd": 0.0,
                                                             "error_code": None}
        images = [runs.image_blob(first, max_side=PHOTO_SIDE)] if first else []
        result = await prompts.run_prompt(BRIEF_PROMPT, {"inputs": inputs_block(run, read["block"])},
                                          purpose="video_brief", images=images, refs=[(runs.SOURCE, run_id)])
        answer = result.json if isinstance(result.json, dict) else {}
        text = str(answer.get("brief") or "").strip()
        if not text:
            raise AppError("video_brief_bad_answer", 502, "The model answered without a text")
        camera = str(answer.get("camera_move") or "").strip()
        camera = camera if camera and catalog.camera_move(camera) else None
        run = runs.get_run(run_id)  # the form may have been saved meanwhile
        old = (run.get("brief") or "").strip()
        meta = {
            "seconds": run.get("duration"), "aspect": run.get("aspect"), "niche": niche,
            "platform": (run.get("platform") or "").strip(), "photo": bool(first), "researched": bool(read["block"]),
            "research_cached": read["cached"], "research_error": read["error_code"], "written_at": db.now(),
            "model_id": result.model_id, "replaced": old or (run.get("brief_meta_json") or {}).get("replaced"),
            "camera_move_suggested": camera,
            "cost_usd": round((result.cost_usd or 0.0) + read["cost_usd"], 6),
        }
        runs.update_run_state(run_id, brief=text[:runs.MAX_BRIEF], brief_meta_json=meta)
    finally:
        _busy.discard(run_id)
    runs.publish(run_id)
    return {"run_id": run_id, "brief": text[:runs.MAX_BRIEF], "camera_move_suggested": camera,
            "cost_usd": meta["cost_usd"], "research_error": read["error_code"]}


def restore_previous(run_id: int) -> dict:
    """"Return the previous text": swap the box and the kept text (free)."""
    run = runs.get_run(run_id)
    meta = dict(run.get("brief_meta_json") or {})
    previous = (meta.get("replaced") or "").strip()
    if not previous:
        raise AppError("video_no_previous_brief", 409, "There is no previous text")
    meta["replaced"] = (run.get("brief") or "").strip() or None
    meta["restored_at"] = db.now()
    runs.update_run_state(run_id, brief=previous, brief_meta_json=meta)
    runs.publish(run_id)
    return runs.get_run(run_id)


def apply_camera_suggestion(run_id: int) -> dict:
    """Take the camera move the writer suggested (one click, free)."""
    run = runs.get_run(run_id)
    code = (run.get("brief_meta_json") or {}).get("camera_move_suggested")
    if not code:
        raise AppError("video_camera_unknown", 400, camera_move=None)
    return runs.update_run(run_id, {"camera_move": code})


__all__ = ["apply_camera_suggestion", "cached_research", "estimate_write", "inputs_block", "restore_previous",
           "write_brief"]
