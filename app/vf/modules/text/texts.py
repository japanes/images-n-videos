"""The words on the picture, written by the model (role ``image_text``). Each button is one choice.

* «Write the words» — the words of this frame (factory ``_rewrite_slide_blocks``): the plan of the
  blocks, the person's instruction, the series around it (switch), the brief and the tone (switches).
  One call, a JSON answer merged back by position: a locked block never changes.
* «Variants» — N variants of one line (factory ``editor_text``): what the person typed plus the
  blocks they ticked, nothing else. N calls, each in the journal.
* «Make it sound human» — a separate button (factory ``overlay_text_humanizer``): every block in
  one call under numbered markers.

Every function takes ``preview`` → ``{system, text}``: exactly what would go to the model, and
nothing is sent. The answer of «Write» and «Human» is put into the design right away; the reply
carries the ``previous`` words so the panel can undo.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from vf.core import db, prompts
from vf.core.errors import AppError
from vf.modules import library
from vf.modules.studio import works as W
from vf.modules.text import common as C
from vf.modules.text import layers as L
from vf.modules.text import store as S

_MARKER_RE = re.compile(r"^\s*<<<\s*(\d+)\s*>>>\s*$", re.MULTILINE)
MAX_CHARS_LIMIT = 300


# ── what the switches read ──────────────────────────────────────────────────

def _language_code(design: dict, body: dict) -> str:
    raw = body.get("language") or (design.get("options_json") or {}).get("language")
    return C.language(raw)


def _max_chars(body: dict) -> int:
    value = body.get("max_chars")
    if value in (None, "", 0, "0"):
        return 0
    return C.count(value, low=1, high=MAX_CHARS_LIMIT)


def brief_of(frame: dict, work: dict) -> str:
    """The brief block's words: the work's general brief, then this frame's own."""
    parts = [str(W.settings_of(work).get("ideas_brief") or "").strip(), str(frame.get("brief") or "").strip()]
    return "\n".join(p for p in parts if p)


def tone_of(design: dict, work: dict) -> str:
    kit_id = design.get("kit_id")
    if kit_id:
        row = db.get("brand_kits", int(kit_id))
        if row is not None:
            return str(row.get("tone") or "").strip()
    snap = S.snapshot_for(design, work) or {}
    return str(snap.get("tone") or "").strip()


def _layer(code: str, values: dict | None = None) -> str:
    return library.render_layer(code, values or {}).strip()


def _note(body: dict) -> str:
    return C.clean_block(body.get("note"), C.MAX_NOTE)


# ── «Write the words» ───────────────────────────────────────────────────────

def plan_text(texts: list[dict]) -> str:
    """The frame's blocks as numbered lines (factory ``flatten_slide_plan``)."""
    lines = []
    for i, block in enumerate(texts, start=1):
        head = f"{i}. [{block['role']}]"
        text = block["text"].strip()
        if block.get("locked"):
            lines.append(f'{head} LOCKED — return this text unchanged: "{text}"')
        elif text:
            lines.append(f'{head} current: "{text}"')
        else:
            lines.append(f"{head} (empty — write it)")
    return "\n".join(lines)


def block_rule(texts: list[dict]) -> str:
    if not texts:
        return _layer("CAROUSEL_BLOCK_COUNT_OPEN")
    roles = ", ".join(f"{i}. {b['role']}" + (" (LOCKED)" if b.get("locked") else "")
                      for i, b in enumerate(texts, start=1))
    return _layer("CAROUSEL_BLOCK_COUNT_FIXED", {"count": len(texts), "roles": roles})


def _series(frame: dict, texts: list[dict]) -> tuple[list[list[dict]], int]:
    """Every frame's blocks by position (this one = the design's words) and this frame's number."""
    rows = W.frames_of(frame["work_id"])
    series, target = [], 1
    for i, r in enumerate(rows, start=1):
        if r["id"] == frame["id"]:
            series.append(texts)
            target = i
        else:
            series.append([b for b in (r.get("text_blocks_json") or []) if isinstance(b, dict)])
    return series or [texts], target


def carousel_context(series: list[list[dict]], target: int) -> str:
    lines: list[str] = []
    for i, blocks in enumerate(series, start=1):
        lines.append(f"Slide {i}:" + ("   <<< THE SLIDE YOU REWRITE" if i == target else ""))
        filled = [b for b in blocks if str(b.get("text") or "").strip()]
        if not filled:
            lines.append("  (empty)")
        for b in filled:
            lines.append(f"  [{b.get('role') or 'body'}] {str(b.get('text')).strip()}")
    return "\n".join(lines) or "(no slides)"


def other_slides(series: list[list[dict]], target: int) -> str:
    lines = [f"- (slide {i}) {str(b.get('text')).strip()}"
             for i, blocks in enumerate(series, start=1) if i != target
             for b in blocks if str(b.get("text") or "").strip()]
    return "\n".join(lines) or "(no other slide has text yet)"


def write_request(design: dict, body: dict) -> tuple[dict, dict]:
    """``(variables, switches)`` of the ``text.write`` prompt as the panel set them."""
    frame = S.frame_of(design)
    work = S.work_of(frame)
    texts = design.get("texts_json") or []
    neighbours = C.flag(body, "use_neighbours")
    use_brief = C.flag(body, "use_brief")
    use_tone = C.flag(body, "use_tone")
    note = _note(body)
    max_chars = _max_chars(body)
    series, target = _series(frame, texts)
    brief_block = _layer("CAROUSEL_SLIDE_REWRITE_BRIEF", {"brief": note}) + "\n\n" if note else ""
    request = _layer("CAROUSEL_SLIDE_REWRITE", {
        "slide_index": target, "slide_count": len(series),
        "plan_text": plan_text(texts) or "(this slide currently has no text)",
        "block_rule": block_rule(texts), "brief_block": brief_block,
        "carousel_context": carousel_context(series, target) if neighbours else
        f"Slide {target}:   <<< THE SLIDE YOU REWRITE\n  (the other pictures are not shared)",
        "other_slides": other_slides(series, target) if neighbours else "(the other pictures are not shared)",
    })
    context = []
    brief = brief_of(frame, work) if use_brief else ""
    if brief:
        context.append(_layer("PROMPT_BLOCK_STORY_BRIEF", {"description": brief}))
    tone = tone_of(design, work) if use_tone else ""
    if tone:
        context.append(_layer("PROMPT_BLOCK_TONE_OF_VOICE", {"tone": tone}))
    if max_chars:
        context.append(_layer("PROMPT_BLOCK_LENGTH_LIMIT", {"max_chars": max_chars}))
    code = _language_code(design, body)
    variables = {"language": C.LANGUAGES[code], "context": "\n\n".join(context) + "\n\n" if context else "",
                 "request": request}
    switches = {"use_neighbours": neighbours, "use_brief": bool(brief), "use_tone": bool(tone),
                "max_chars": max_chars, "language": code, "note": bool(note)}
    return variables, switches


def merge_blocks(answer: Any, plan: list[dict]) -> list[dict]:
    """The model's blocks folded back onto the plan by position (factory ``merge_block_plan``)."""
    model = [b for b in (answer if isinstance(answer, list) else []) if isinstance(b, dict)]
    if not plan:
        out = [{"role": b.get("role"), "size": b.get("size"), "text": C.clean_overlay_text(b.get("text"))}
               for b in model]
        return L.normalize_texts([b for b in out if b["text"]][:C.MAX_TEXTS])
    merged = []
    for i, block in enumerate(plan):
        if block.get("locked"):
            merged.append(block)
            continue
        text = C.clean_overlay_text(model[i].get("text")) if i < len(model) else ""
        merged.append({**block, "text": text or block["text"]})
    return L.normalize_texts(merged)


def _put_texts(design: dict, texts: list[dict]) -> None:
    S.update(design["id"], {"texts_json": texts, "layers_json": L.bind_texts(design.get("layers_json") or [], texts),
                            "status": "draft"})


async def write(design_id: int, body: Any) -> dict:
    """``{use_neighbours, use_brief, use_tone, max_chars, language, note, preview}``."""
    body = body if isinstance(body, dict) else {}
    design = S.design_row(design_id)
    variables, switches = write_request(design, body)
    if C.flag(body, "preview"):
        return {"system": "", "text": prompts.render(C.PROMPT_WRITE, **variables).text, "switches": switches}
    result = await prompts.run_prompt(C.PROMPT_WRITE, variables, purpose=C.PURPOSE_WRITE, refs=S.refs_of(design))
    data = result.json if isinstance(result.json, dict) else {}
    previous = design.get("texts_json") or []
    texts = merge_blocks(data.get("blocks"), previous)
    S.add_cost(design_id, result.cost_usd)
    if not any(t["text"] for t in texts):
        raise AppError("text_empty", 502, "The model returned no words")
    _put_texts(design, texts)
    return {"texts": texts, "previous": previous, "cost_usd": round(result.cost_usd or 0, 6),
            "model_id": result.model_id}


# ── «Variants» ──────────────────────────────────────────────────────────────

def variants_request(design: dict, body: dict) -> tuple[str, str]:
    """``(system, prompt)``: typed text first, then the ticked blocks in the factory's order."""
    frame = S.frame_of(design)
    work = S.work_of(frame)
    parts = []
    typed = _note(body)
    if typed:
        parts.append(typed)
    if C.flag(body, "use_language"):
        parts.append(_layer("PROMPT_BLOCK_LANGUAGE", {"language_name": C.LANGUAGES[_language_code(design, body)]}))
    max_chars = _max_chars(body)
    if max_chars:
        parts.append(_layer("PROMPT_BLOCK_LENGTH_LIMIT", {"max_chars": max_chars}))
    if C.flag(body, "use_tone"):
        tone = tone_of(design, work)
        if tone:
            parts.append(_layer("PROMPT_BLOCK_TONE_OF_VOICE", {"tone": tone}))
    if C.flag(body, "use_brief"):
        brief = brief_of(frame, work)
        if brief:
            parts.append(_layer("PROMPT_BLOCK_STORY_BRIEF", {"description": brief}))
    if C.flag(body, "use_rules"):
        parts.append(_layer("PROMPT_BLOCK_OVERLAY_RULES"))
    feedback = C.clean_block(body.get("feedback"), C.MAX_NOTE)
    if feedback:
        parts.append(_layer("PROMPT_BLOCK_FEEDBACK", {"feedback": feedback}))
    system = _layer("PROMPT_BLOCK_OVERLAY_SYSTEM") if C.flag(body, "use_system") else ""
    return system, "\n\n".join(parts)


async def variants(design_id: int, body: Any) -> dict:
    """``{note, count 1..4, use_system, use_rules, use_language, use_tone, use_brief, max_chars,
    feedback, language, preview}`` → ``{variants: [text], errors, cost_usd}``. Nothing is put into
    the design: the person picks a variant."""
    body = body if isinstance(body, dict) else {}
    design = S.design_row(design_id)
    n = C.count(body.get("count", 1), high=C.MAX_VARIANTS)
    system, request = variants_request(design, body)
    if not request.strip():
        raise AppError("empty_prompt", 400, "Type what the line is about or tick a block")
    if C.flag(body, "preview"):
        return {"system": system, "text": prompts.render(C.PROMPT_VARIANTS, request=request).text, "count": n}
    refs = S.refs_of(design)
    results = await asyncio.gather(*[
        prompts.run_prompt(C.PROMPT_VARIANTS, {"request": request}, purpose=C.PURPOSE_VARIANTS,
                           system=system or None, refs=refs)
        for _ in range(n)], return_exceptions=True)
    texts, errors, cost, model_id = [], [], 0.0, None
    for result in results:
        if isinstance(result, AppError):
            errors.append({"code": result.code, "message": getattr(result, "raw", "") or result.message})
            continue
        if isinstance(result, BaseException):
            raise result
        cost += result.cost_usd or 0
        model_id = result.model_id
        line = C.clean_overlay_text(result.text)
        if line:
            texts.append(line[:C.MAX_TEXT])
    S.add_cost(design_id, cost)
    if not texts and errors:
        first = next(r for r in results if isinstance(r, AppError))
        raise first
    return {"variants": texts, "errors": errors, "cost_usd": round(cost, 6), "model_id": model_id}


# ── «Make it sound human» ───────────────────────────────────────────────────

def humanize_targets(design: dict, body: dict) -> list[tuple[int, dict]]:
    wanted = body.get("text_ids")
    ids = {str(x) for x in wanted} if isinstance(wanted, list) and wanted else None
    picked = [t for t in design.get("texts_json") or []
              if t["text"].strip() and not t.get("locked") and (ids is None or t["id"] in ids)]
    return list(enumerate(picked, start=1))


def humanize_request(design: dict, body: dict) -> tuple[dict, list[tuple[int, dict]]]:
    numbered = humanize_targets(design, body)
    if not numbered:
        raise AppError("no_text", 400, "There are no words to rewrite")
    total = sum(len(t["text"]) for _, t in numbered)
    if total > C.MAX_HUMANIZE_CHARS:
        raise AppError("too_long", 400, "Too many words for one rewrite", max=C.MAX_HUMANIZE_CHARS)
    head = _layer("SLIDE_TEXT_HUMANIZER") + "\n"
    draft = head + "\n".join(f"\n<<<{n}>>>\n{t['text']}" for n, t in numbered)
    language = C.LANGUAGES[_language_code(design, body)] if C.flag(body, "use_language") else ""
    return {"draft": draft, "language": language}, numbered


def parse_markers(answer: str) -> dict[int, str]:
    out: dict[int, str] = {}
    matches = list(_MARKER_RE.finditer(answer or ""))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer)
        out[int(match.group(1))] = answer[match.end():end].strip()
    return out


async def humanize(design_id: int, body: Any) -> dict:
    """``{text_ids?, use_language, language, preview}`` → the rewritten words put into the design."""
    body = body if isinstance(body, dict) else {}
    design = S.design_row(design_id)
    variables, numbered = humanize_request(design, body)
    if C.flag(body, "preview"):
        return {"system": "", "text": prompts.render(C.PROMPT_HUMANIZE, **variables).text, "blocks": len(numbered)}
    result = await prompts.run_prompt(C.PROMPT_HUMANIZE, variables, purpose=C.PURPOSE_HUMANIZE,
                                      refs=S.refs_of(design))
    S.add_cost(design_id, result.cost_usd)
    rewritten = parse_markers(result.text or "")
    previous = design.get("texts_json") or []
    by_id = {t["id"]: n for n, t in numbered}
    texts, replaced = [], 0
    for t in previous:
        n = by_id.get(t["id"])
        candidate = C.clean_overlay_text(rewritten.get(n) or "") if n else ""
        if candidate:
            replaced += 1
            texts.append({**t, "text": candidate[:C.MAX_TEXT]})
        else:
            texts.append(t)
    if replaced:
        _put_texts(design, L.normalize_texts(texts))
    return {"texts": texts if replaced else previous, "previous": previous, "replaced": replaced,
            "asked": len(numbered), "cost_usd": round(result.cost_usd or 0, 6), "model_id": result.model_id}


__all__ = ["humanize", "merge_blocks", "parse_markers", "plan_text", "variants", "write"]
