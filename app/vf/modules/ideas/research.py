"""The niche research: what the leading companies of a niche are doing in pictures now.

Optional and switched on by the person (its own price next to the switch). One
Gemini call with Google Search (role ``research``, prompt ``ideas.research``,
purpose ``shot_research``). The answer is a short English summary for the next
prompt plus the pages Google Search used, shown to the person as links.

The same niche + platform is kept for ``ideas.research_cache_days`` days (0 = never
reuse), so it is not paid twice. A failed search does not stop the ideas: the set
is written without the research and the card says why.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from vf.core import db, prompts
from vf.core.errors import AppError
from vf.modules.ideas import common as C

log = logging.getLogger("vf.ideas")


def _niche(value: str | None) -> str:
    return C.clean_line(value, C.MAX_RESEARCH_NICHE)


def _platform(value: str | None) -> str:
    return C.clean_line(value, C.MAX_RESEARCH_PLATFORM)


def cached(niche: str | None, platform: str | None) -> dict | None:
    """The research of this niche + platform younger than the setting, or None."""
    days = C.cache_days()
    key = C.key_of(_niche(niche))
    if days <= 0 or not key:
        return None
    cutoff = C.stamp(datetime.now(UTC) - timedelta(days=days))
    return db.fetch_one("SELECT * FROM ideas_research WHERE niche_key = ? AND platform_key = ? AND created_at >= ?",
                        (key, C.key_of(_platform(platform)), cutoff))


def clean_sources(raw: list | None) -> list[dict]:
    """Links that open in a browser, each once, at most ``MAX_SOURCES``."""
    out: list[dict] = []
    seen: set[str] = set()
    for src in raw or []:
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or "").strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        out.append({"title": C.clean_line(src.get("title"), 200) or url, "url": url})
        if len(out) >= C.MAX_SOURCES:
            break
    return out


def block(niche: str, summary: str) -> str:
    """The research as the brief carries it; "" when there is none."""
    if not (summary or "").strip():
        return ""
    return "\n".join([C.RESEARCH_HEADING, f"NICHE: {_niche(niche)}", "", summary.strip()]).strip()


def _from_cache(row: dict) -> dict:
    return {"summary": row["summary"], "sources": row.get("sources_json") or [], "cached": True,
            "created_at": row["created_at"], "error_code": None, "error": None, "cost_usd": 0.0,
            "model_id": row.get("model_id"), "niche": row["niche"], "platform": row["platform"]}


async def run(niche: str, platform: str, *, refs: list[tuple[str, int]]) -> dict:
    """Research from the cache or a paid search. Never raises an app error: it is returned in the result."""
    niche, platform = _niche(niche), _platform(platform)
    row = cached(niche, platform)
    if row is not None:
        return _from_cache(row)
    out = {"summary": "", "sources": [], "cached": False, "created_at": db.now(), "error_code": None,
           "error": None, "cost_usd": 0.0, "model_id": None, "niche": niche, "platform": platform}
    from vf.modules import library

    request = library.render_layer("SHOT_RESEARCH_INPUT", {"niche": niche, "platform": platform}).strip()
    try:
        result = await prompts.run_prompt(
            C.PROMPT_RESEARCH, {"request": request, "today": datetime.now(UTC).date().isoformat()},
            purpose=C.PURPOSE_RESEARCH, search=True, refs=refs)
    except AppError as err:   # a Google refusal, or the research role has no fitting model
        log.warning("ideas research failed: %s", err.code)
        out.update(error_code=err.code, error=getattr(err, "raw", None) or err.message)
        return out
    summary = C.clean_block(result.text, C.MAX_RESEARCH_TEXT)
    out.update(cost_usd=round(result.cost_usd or 0.0, 6), model_id=result.model_id,
               sources=clean_sources(result.sources))
    if not summary:
        out["error_code"] = "empty_answer"
        return out
    out["summary"] = summary
    db.execute(
        "INSERT INTO ideas_research (niche_key, platform_key, niche, platform, summary, sources_json, model_id, "
        "cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (niche_key, platform_key) DO UPDATE SET "
        "niche = excluded.niche, platform = excluded.platform, summary = excluded.summary, "
        "sources_json = excluded.sources_json, model_id = excluded.model_id, cost_usd = excluded.cost_usd, "
        "created_at = excluded.created_at",
        (C.key_of(niche), C.key_of(platform), niche, platform, summary, _json(out["sources"]), result.model_id,
         out["cost_usd"], out["created_at"]))
    return out


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


__all__ = ["block", "cached", "clean_sources", "run"]
