"""The only way the app talks to Gemini.

``generate()`` picks the model (asked for, by role, or the default), paces the
call through the shared limiter, writes every attempt to the spend journal,
retries what is worth retrying, and returns text, JSON or pictures.

Retries follow factory's ``gemini_service``:
- ``google.max_attempts`` attempts in total for errors;
- rate limits (429 / quota) wait at least 60 s, or longer if Google says so;
- other transient errors back off 1 s, 2 s, 4 s ... up to 30 s;
- an answer without a picture (not a block) is asked again after a pause,
  from a separate budget;
- a safety block is never repeated and costs $0.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from vf.core import db, models_registry, settings
from vf.core.config import get_config
from vf.core.google import credentials, journal, stub
from vf.core.google.errors import GoogleCallError, classify, enum_name, refusal_detail
from vf.core.google.limiter import limiter

log = logging.getLogger("vf.google")

settings.define("google.refusal_retries", 2, group="google", kind="int", min=0, max=5)
settings.define("google.refusal_retry_seconds", 30, group="google", kind="int", min=0, max=300)

RATE_LIMIT_PAUSE = 60.0
BASE_BACKOFF = 1.0
MAX_BACKOFF = 30.0


@dataclass
class Blob:
    """Bytes sent to the model (a picture, a video, a PDF)."""

    data: bytes
    mime: str
    file_id: int | None = None

    def summary(self) -> dict:
        return {
            "mime": self.mime,
            "size": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest()[:16],
            "file_id": self.file_id,
        }


def blob_from_file(file_id: int) -> Blob:
    from vf.core import files

    row = files.get(file_id)
    return Blob(files.read_bytes(file_id), row["mime"], file_id)


@dataclass
class PromptInfo:
    code: str
    version: int


@dataclass
class GenerateResult:
    text: str = ""
    json: Any = None
    images: list[tuple[bytes, str]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thinking: int = 0
    cost_usd: float = 0.0
    call_ids: list[int] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    finish_reason: str = ""
    model_id: str = ""
    stub: bool = False


@dataclass
class _Answer:
    text: str = ""
    images: list[tuple[bytes, str]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thinking: int = 0
    queries: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    blocked: bool = False
    refusal: str = ""


# ── helpers ─────────────────────────────────────────────────────────────────


def _cancelled(cancel: Callable[[], bool] | None) -> bool:
    try:
        return bool(cancel and cancel())
    except Exception:
        return False


async def _sleep(seconds: float, cancel: Callable[[], bool] | None = None) -> None:
    """Sleep in small steps so a cancelled job stops waiting."""
    left = float(seconds)
    while left > 0:
        if _cancelled(cancel):
            raise GoogleCallError("cancelled", "Cancelled while waiting to retry")
        step = min(left, 1.0)
        await asyncio.sleep(step)
        left -= step


def _check_daily_cap() -> None:
    cap = float(settings.get("google.daily_cap_usd") or 0)
    if cap > 0 and journal.spent_today() >= cap:
        raise GoogleCallError("daily_cap", f"Daily spending cap ${cap:.2f} reached", cap=cap)


def _pick_model(response: str, model_id: str | None, role: str | None) -> dict:
    if response == "image":
        return models_registry.resolve("image", model_id)
    if model_id:
        return models_registry.resolve("text", model_id)
    if role:
        return models_registry.model_for_role(role)
    return models_registry.default_for("text")


def parse_json_text(text: str) -> Any:
    """JSON from a model answer, tolerating code fences and chatter around it."""
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = s.find(open_ch), s.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except ValueError:
                continue
    raise ValueError("answer is not JSON")


def _usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return 0, 0, 0
    prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
    tool = int(getattr(usage, "tool_use_prompt_token_count", 0) or 0)
    out = int(getattr(usage, "candidates_token_count", 0) or 0)
    thoughts = int(getattr(usage, "thoughts_token_count", 0) or 0)
    return prompt + tool, out + thoughts, thoughts


def _read_answer(response: Any) -> _Answer:
    """Normalize a google-genai response. Tokens are read first: a refusal is billed too."""
    ans = _Answer()
    ans.tokens_in, ans.tokens_out, ans.tokens_thinking = _usage(response)
    candidates = getattr(response, "candidates", None) or []
    first = candidates[0] if candidates else None
    ans.finish_reason = enum_name(getattr(first, "finish_reason", None))
    texts: list[str] = []
    for part in getattr(getattr(first, "content", None), "parts", None) or []:
        if getattr(part, "thought", False):
            continue
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            ans.images.append((inline.data, inline.mime_type or "image/png"))
        elif getattr(part, "text", None):
            texts.append(part.text)
    ans.text = "".join(texts)
    grounding = getattr(first, "grounding_metadata", None)
    if grounding is not None:
        ans.queries = [q for q in (getattr(grounding, "web_search_queries", None) or []) if q]
        for chunk in getattr(grounding, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            if web is not None and getattr(web, "uri", None):
                ans.sources.append({"title": web.title or web.domain or web.uri, "url": web.uri})
    detail, blocked = refusal_detail(response)
    ans.blocked = blocked
    ans.refusal = detail
    return ans


def _build_config(*, model: dict, system: str | None, response: str, schema: dict | None,
                  aspect_ratio: str | None, image_size: str | None, search: bool,
                  temperature: float | None, max_output_tokens: int | None, thinking_level: str | None):
    from google.genai import types

    cfg: dict[str, Any] = {}
    if system:
        cfg["system_instruction"] = system
    if temperature is not None:
        cfg["temperature"] = temperature
    if max_output_tokens:
        cfg["max_output_tokens"] = max_output_tokens
    if response == "json" and not search:
        # Structured output and Google Search do not mix on every model; with
        # search on, the prompt asks for JSON and the answer is parsed leniently.
        cfg["response_mime_type"] = "application/json"
        if schema:
            cfg["response_json_schema"] = schema
    if response == "image":
        cfg["response_modalities"] = ["IMAGE", "TEXT"]
        image_cfg = {k: v for k, v in (("aspect_ratio", aspect_ratio), ("image_size", image_size)) if v}
        if image_cfg:
            cfg["image_config"] = types.ImageConfig(**image_cfg)
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if thinking_level and (model.get("caps") or {}).get("thinking"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level.upper())
    return types.GenerateContentConfig(**cfg)


def _build_contents(contents: Sequence[str | Blob]):
    from google.genai import types

    parts = []
    for item in contents:
        if isinstance(item, Blob):
            parts.append(types.Part.from_bytes(data=item.data, mime_type=item.mime))
        else:
            parts.append(types.Part.from_text(text=str(item)))
    return [types.Content(role="user", parts=parts)]


def _search_requests(model: dict, queries: list[str]) -> int:
    unit = (model.get("price") or {}).get("search_unit", "query")
    if unit == "prompt":
        return 1 if queries else 0
    return len(queries)


def _response_summary(response: str, ans: _Answer) -> Any:
    out: dict[str, Any] = {"finish_reason": ans.finish_reason}
    if response == "image":
        out["images"] = [{"mime": m, "size": len(b)} for b, m in ans.images]
        if ans.text:
            out["text"] = ans.text
    else:
        out["text"] = ans.text
    if ans.queries:
        out["search_queries"] = ans.queries
    if ans.sources:
        out["sources"] = ans.sources
    if ans.refusal:
        out["refusal"] = ans.refusal
    return out


# ── main entry ──────────────────────────────────────────────────────────────


async def generate(*, purpose: str, contents: Sequence[str | Blob], model_id: str | None = None,
                   role: str | None = None, system: str | None = None, prompt: PromptInfo | None = None,
                   response: str = "text", schema: dict | None = None, aspect_ratio: str | None = None,
                   image_size: str | None = None, search: bool = False, temperature: float | None = None,
                   max_output_tokens: int | None = None, thinking_level: str | None = None,
                   refs: Sequence[tuple[str, int]] = (), cancel: Callable[[], bool] | None = None,
                   variant_index: int = 0) -> GenerateResult:
    """One Gemini request (with retries). Raises ``GoogleCallError`` on failure."""
    if response not in ("text", "json", "image"):
        raise ValueError(f"bad response kind {response!r}")
    is_stub = get_config().stub
    if not is_stub and not credentials.has_key():
        raise GoogleCallError("no_key", "No Google key is connected")
    _check_daily_cap()
    model = _pick_model(response, model_id, role)
    region = model.get("region") or "global"
    kind = "image" if response == "image" else "text"

    blobs = [c for c in contents if isinstance(c, Blob)]
    texts = [str(c) for c in contents if not isinstance(c, Blob)]
    prompt_text = "\n\n".join(texts)
    attachments = [b.summary() for b in blobs] or None
    request_summary = {
        "model": model["id"], "region": region, "response": response, "aspect_ratio": aspect_ratio,
        "image_size": image_size, "search": search, "temperature": temperature,
        "max_output_tokens": max_output_tokens, "thinking_level": thinking_level,
        "system": system, "schema": schema,
    }
    request_summary = {k: v for k, v in request_summary.items() if v not in (None, False)}

    config = None
    google_contents = None
    if not is_stub:
        config = _build_config(model=model, system=system, response=response, schema=schema,
                               aspect_ratio=aspect_ratio, image_size=image_size, search=search,
                               temperature=temperature, max_output_tokens=max_output_tokens,
                               thinking_level=thinking_level)
        google_contents = _build_contents(contents)

    max_attempts = int(settings.get("google.max_attempts"))
    refusals_left = int(settings.get("google.refusal_retries"))
    errors_used = 0
    attempt = 0
    call_ids: list[int] = []
    total_in = total_out = total_thinking = 0
    total_cost = 0.0

    def fail(err: GoogleCallError) -> GoogleCallError:
        err.call_ids = list(call_ids)
        err.details["call_ids"] = list(call_ids)
        return err

    while True:
        attempt += 1
        if _cancelled(cancel):
            raise fail(GoogleCallError("cancelled", "Cancelled before the request"))
        call_id = journal.start_call(
            kind=kind, purpose=purpose, model=model, region=region, role=role,
            prompt_code=prompt.code if prompt else None, prompt_version=prompt.version if prompt else None,
            prompt_text=prompt_text, request=request_summary, attachments=attachments, attempt=attempt,
            refs=refs, stub=is_stub,
        )
        call_ids.append(call_id)
        try:
            async with limiter.slot():
                if is_stub:
                    sa = await stub.answer(prompt=prompt_text, response=response, schema=schema,
                                           aspect_ratio=aspect_ratio, image_size=image_size, search=search,
                                           index=variant_index)
                    ans = _Answer(text=sa.text, images=sa.images, queries=sa.queries, sources=sa.sources,
                                  finish_reason=sa.finish_reason, blocked=sa.blocked, refusal=sa.refusal)
                    tiers = (model.get("price") or {}).get("image_output_tokens") or {}
                    ans.tokens_in, ans.tokens_out, ans.tokens_thinking = stub.usage(
                        prompt_text + (system or ""), len(blobs), sa, int(tiers.get(image_size or "1K") or 1120))
                else:
                    from vf.core.google.client import get_client

                    client = get_client(region)
                    timeout = int(settings.get("google.timeout_seconds")) + 15
                    raw = await asyncio.wait_for(
                        client.aio.models.generate_content(model=model["id"], contents=google_contents,
                                                           config=config),
                        timeout=timeout,
                    )
                    ans = _read_answer(raw)
        except asyncio.CancelledError:
            journal.finish_call(call_id, status="cancelled", error_code="cancelled",
                                error_text="Cancelled while waiting for Google; Google may still bill it.")
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is journaled, then sorted
            if isinstance(exc, stub.StubFailure):
                err = GoogleCallError(exc.code, f"[stub] simulated {exc.code}",
                                      retryable=exc.code in ("rate_limited", "server_error", "network", "timeout"))
            else:
                err = classify(exc)
            journal.finish_call(call_id, status="error", error_code=err.code, error_text=err.raw,
                                http_status=err.http_status)
            log.warning("Google call %s failed (attempt %d, %s): %s", purpose, attempt, err.code, err.raw[:300])
            errors_used += 1
            if not err.retryable or errors_used >= max_attempts:
                raise fail(err) from exc
            if err.code == "rate_limited":
                pause = max(err.retry_after or 0.0, RATE_LIMIT_PAUSE)
            else:
                pause = min(BASE_BACKOFF * (2 ** (errors_used - 1)), MAX_BACKOFF)
            await _sleep(pause, cancel)
            continue

        search_requests = _search_requests(model, ans.queries) if search else 0
        common = dict(tokens_in=ans.tokens_in, tokens_out=ans.tokens_out, tokens_thinking=ans.tokens_thinking,
                      search_queries=len(ans.queries) or None, search_requests=search_requests,
                      response=_response_summary(response, ans))

        if ans.blocked:
            journal.finish_call(call_id, status="blocked", error_code="safety_blocked", error_text=ans.refusal,
                                **common)
            raise fail(GoogleCallError("safety_blocked", ans.refusal or "Blocked by Google safety filters",
                                       blocked=True))

        empty = (response == "image" and not ans.images) or (response != "image" and not ans.text.strip())
        if empty:
            row = journal.finish_call(call_id, status="error", error_code="refused",
                                      error_text=ans.refusal or "The answer was empty", **common)
            total_cost += row.get("cost_usd") or 0
            if refusals_left > 0:
                refusals_left -= 1
                await _sleep(float(settings.get("google.refusal_retry_seconds")), cancel)
                continue
            raise fail(GoogleCallError("refused", ans.refusal or "The model answered without a result"))

        parsed = None
        if response == "json":
            try:
                parsed = parse_json_text(ans.text)
            except ValueError:
                row = journal.finish_call(call_id, status="error", error_code="bad_answer",
                                          error_text="The answer is not valid JSON", **common)
                total_cost += row.get("cost_usd") or 0
                errors_used += 1
                if errors_used >= max_attempts:
                    raise fail(GoogleCallError("bad_answer", ans.text[:2000])) from None
                await _sleep(min(BASE_BACKOFF * (2 ** (errors_used - 1)), MAX_BACKOFF), cancel)
                continue

        row = journal.finish_call(call_id, status="success", **common)
        total_cost += row.get("cost_usd") or 0
        total_in += ans.tokens_in
        total_out += ans.tokens_out
        total_thinking += ans.tokens_thinking
        return GenerateResult(
            text=ans.text, json=parsed, images=ans.images, tokens_in=total_in, tokens_out=total_out,
            tokens_thinking=total_thinking, cost_usd=round(_sum_cost(call_ids), 6), call_ids=call_ids,
            sources=ans.sources, search_queries=ans.queries, finish_reason=ans.finish_reason,
            model_id=model["id"], stub=is_stub,
        )


def _sum_cost(call_ids: list[int]) -> float:
    if not call_ids:
        return 0.0
    marks = ",".join("?" for _ in call_ids)
    return float(db.fetch_value(f"SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE id IN ({marks})",
                                call_ids, 0.0))


async def list_models(*, region: str = "global", purpose: str = "connection_check") -> list[dict]:
    """Base models visible to the project. Free; journaled with cost 0."""
    is_stub = get_config().stub
    if not is_stub and not credentials.has_key():
        raise GoogleCallError("no_key", "No Google key is connected")
    call_id = journal.start_call(kind="list_models", purpose=purpose, region=region,
                                 request={"region": region, "query_base": True}, stub=is_stub)
    try:
        if is_stub:
            await asyncio.sleep(stub.delay())
            found = [{"name": m["id"], "display_name": m["title"]} for m in models_registry.list_models()]
        else:
            from google.genai import types

            from vf.core.google.client import get_client

            client = get_client(region)
            found = []
            pager = await client.aio.models.list(config=types.ListModelsConfig(query_base=True, page_size=200))
            async for m in pager:
                name = (m.name or "").rsplit("/", 1)[-1]
                found.append({"name": name, "display_name": m.display_name, "version": m.version})
    except asyncio.CancelledError:
        journal.finish_call(call_id, status="cancelled", cost_usd=0)
        raise
    except Exception as exc:  # noqa: BLE001
        err = classify(exc)
        journal.finish_call(call_id, status="error", error_code=err.code, error_text=err.raw,
                            http_status=err.http_status, cost_usd=0)
        err.call_ids = [call_id]
        raise err from exc
    journal.finish_call(call_id, status="success", response={"count": len(found)}, cost_usd=0)
    return found
