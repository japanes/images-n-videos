"""One press of «Write ideas»: the card in the chat, the research, the ideas, the first frame.

The start (``start``) checks the brief, puts the card into the chat and queues the
job ``ideas.write``. The job:

1. the niche research, when the person switched it on (from the cache or one
   paid search); the card shows it as soon as it is there. A failed search is
   written on the card and the ideas go on without it;
2. the ideas: one Gemini call (role ``shot_ideas``, prompt ``ideas.shot_ideas``)
   with the brief, the setting, the research and the brief's pictures; the answer
   is a concept and one prompt per frame;
3. when «Draw the first frame at once» is on — the studio draws the cards as a
   series: the first frame now, the others after «Accept».

Every call is journaled with the refs ("ideas_set", id), ("chat", chat id) and
("chat_message", card id), so the spend screen finds them from the set and from the chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from vf.core import db, jobs, models_registry, prompts
from vf.core.errors import AppError
from vf.modules.ideas import brief as B
from vf.modules.ideas import common as C
from vf.modules.ideas import draw as D
from vf.modules.ideas import research as R
from vf.modules.ideas import scene as SC
from vf.modules.ideas import sets as S

log = logging.getLogger("vf.ideas")


def refs_of(row: dict) -> list[tuple[str, int]]:
    out = [(C.REF_SET, row["id"]), ("chat", row["chat_id"])]
    if row.get("message_id"):
        out.append(("chat_message", row["message_id"]))
    return out


# ── the answer ──────────────────────────────────────────────────────────────

def answer_json(result: Any) -> dict:
    """The JSON of the answer; a text answer is read from its first ``{`` to its last ``}``."""
    data = result.json
    text = result.text or ""
    if data is None and "{" in text:
        try:
            data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except ValueError:
            data = None
    return data if isinstance(data, dict) else {}


def parse(result: Any, *, count: int) -> tuple[dict, list[dict]]:
    """``(concept, cards)`` from the model's answer; an answer without a single prompt is an error."""
    data = answer_json(result)
    concept = data.get("concept") if isinstance(data.get("concept"), dict) else {}
    raw = data.get("images") if isinstance(data.get("images"), list) else data.get("ideas")
    cards: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        prompt = C.clean_block(item.get("prompt"), C.MAX_PROMPT)
        if not prompt:
            continue
        cards.append({"n": len(cards) + 1, "title": C.clean_line(item.get("title"), C.MAX_TITLE),
                      "prompt": prompt, "edited": False, "work_id": None, "frame_id": None,
                      "message_id": None, "drawn_at": None})
    limit = count if count else C.MAX_COUNT
    cards = cards[:min(limit, C.MAX_COUNT)]
    if not cards:
        raise AppError("ideas_empty", 502, "The model returned no prompts")
    return ({"name": C.clean_line(concept.get("name"), C.MAX_CONCEPT_NAME),
             "direction": C.clean_block(concept.get("direction"), C.MAX_DIRECTION)}, cards)


# ── the start ───────────────────────────────────────────────────────────────

def _flag(body: dict, name: str) -> bool:
    value = body.get(name)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise AppError("bad_request", 400, "A switch is true or false", field=name)
    return value


def start(body: Any) -> dict:
    """``{set, message}``: the card is in the chat and the job is queued."""
    from vf.modules import chat
    from vf.modules.chat import store

    if not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    try:
        chat_id = int(body.get("chat_id"))
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "chat_id is needed") from None
    store.chat_row(chat_id)
    brief = B.clean(body.get("brief"))
    picked = SC.normalize(body.get("scene"))
    research = _flag(body, "research")
    options = {"draw_first": _flag(body, "draw_first"), "product_to_frames": _flag(body, "product_to_frames")}
    models_registry.model_for_role(C.ROLE_IDEAS)          # a refusal now, not after the card is posted
    if research:
        models_registry.model_for_role(C.ROLE_RESEARCH)
    set_id = S.create(chat_id, brief=brief, scene=picked, research=research, options=options)
    row = S.set_row(set_id)
    message = chat.post_message(chat_id, kind=C.MESSAGE_KIND, type="result", text=brief["niche"],
                                data=S.view(row), status="running")
    job_id = jobs.enqueue(C.JOB_WRITE, {"set_id": set_id}, ref_type=C.REF_SET, ref_id=set_id,
                          title=brief["niche"])
    S.update(set_id, {"message_id": message["id"], "job_id": job_id})
    out = S.sync(set_id)
    return {"set": out, "message": chat.get_message(message["id"])}


# ── the job ─────────────────────────────────────────────────────────────────

async def _research(ctx: jobs.JobContext, row: dict) -> str:
    brief = row.get("brief_json") or {}
    ctx.progress(0.1, "research", force=True)
    found = await R.run(brief.get("niche") or "", brief.get("platform") or "", refs=refs_of(row))
    S.update(row["id"], {"research_json": found})
    S.refresh_cost(row["id"])
    S.sync(row["id"])
    ctx.raise_if_cancelled()
    return R.block(found.get("niche") or brief.get("niche") or "", found.get("summary") or "")


async def _write(ctx: jobs.JobContext, set_id: int) -> dict:
    row = S.set_row(set_id)
    research_block = await _research(ctx, row) if row.get("research") else ""
    brief = row.get("brief_json") or {}
    images, product_count, visual_count = B.pictures(brief)
    text = B.user_input(brief, product_count=product_count, visual_count=visual_count,
                        research_block=research_block, scene_block=SC.as_block(row.get("scene_json") or {}))
    ctx.progress(0.4, "ideas", force=True)
    result = await prompts.run_prompt(C.PROMPT_IDEAS, {"user_input": text}, purpose=C.PURPOSE_IDEAS,
                                      images=images, refs=refs_of(row), cancel=lambda: ctx.cancel_requested)
    ctx.raise_if_cancelled()
    concept, cards = parse(result, count=int(brief.get("count") or 0))
    S.update(set_id, {"concept_json": concept, "images_json": cards, "status": "done", "error_code": None,
                      "error": None, "model_id": result.model_id,
                      "prompt_version": prompts.get(C.PROMPT_IDEAS).version})
    S.refresh_cost(set_id)
    S.sync(set_id)
    if (row.get("options_json") or {}).get("draw_first"):
        ctx.progress(0.9, "draw", force=True)
        D.draw_safely(set_id)
    # chat_id / message_id: the jobs page leads «Open» to the card (web/plugins/ideas-jobrefs.js)
    done = S.set_row(set_id)
    return {"set_id": set_id, "cards": len(cards), "chat_id": done.get("chat_id"),
            "message_id": done.get("message_id")}


@jobs.handler(C.JOB_WRITE, group="text", recover="interrupt")
async def run_write(ctx: jobs.JobContext) -> dict | None:
    set_id = int(ctx.payload.get("set_id") or 0)
    if db.get("ideas_sets", set_id) is None:
        return {"skipped": "gone"}
    try:
        return await _write(ctx, set_id)
    except (asyncio.CancelledError, jobs.JobCancelled):
        if ctx.cancel_requested:   # a stop of the app leaves the set to ``sweep`` at the next start
            _close(set_id, "cancelled", "cancelled", None)
        raise
    except AppError as exc:
        _close(set_id, "error", exc.code, getattr(exc, "raw", None) or exc.message)
        raise
    except Exception as exc:
        _close(set_id, "error", getattr(exc, "code", None) or "internal", getattr(exc, "raw", None) or str(exc))
        raise


def _close(set_id: int, status: str, code: str | None, error: str | None) -> None:
    try:
        S.update(set_id, {"status": status, "error_code": code, "error": error})
        S.refresh_cost(set_id)
        S.sync(set_id)
    except AppError:
        log.warning("ideas set %s: could not be closed as %s", set_id, status)


__all__ = ["answer_json", "parse", "refs_of", "run_write", "start"]
