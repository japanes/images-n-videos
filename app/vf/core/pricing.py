"""What a Google call costs, by the registry price. One function per meter.

These are estimates from the price list; the exact bill is in Google Billing.
The same functions price a finished call (journal) and a button before it is
pressed, so the two cannot drift apart.
"""

from __future__ import annotations

from vf.core import db

PER_MILLION = 1_000_000

# Fallback output tokens of one picture by size tier, when the model's own
# price has no number for it and the journal has no history yet.
DEFAULT_IMAGE_TOKENS = {"512": 747, "1K": 1120, "2K": 1680, "4K": 2520}
# Rough input tokens of one attached picture (Gemini bills ~258 per tile).
IMAGE_INPUT_TOKENS = 560
TEXT_PROMPT_TOKENS = 1500
TEXT_ANSWER_TOKENS = 1200


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def tokens_cost(price: dict, tokens_in: int | None, tokens_out: int | None) -> float:
    return (
        (tokens_in or 0) * _num(price.get("input_per_1m")) / PER_MILLION
        + (tokens_out or 0) * _num(price.get("output_per_1m")) / PER_MILLION
    )


def search_cost(price: dict, requests: int | None) -> float:
    return (requests or 0) * _num(price.get("search_per_request"))


def veo_cost(price: dict, seconds: float | None, resolution: str | None) -> float:
    table = {str(k).lower(): v for k, v in (price.get("per_second") or {}).items()}
    return _num(seconds) * _num(table.get(str(resolution or "720p").lower()))


def omni_cost(price: dict, tokens_in: int | None, tokens_out: int | None,
              output_seconds: float | None = None) -> float:
    """Omni bills its video as output tokens; without a count, tokens/second x seconds."""
    if not tokens_out and output_seconds:
        tokens_out = int(_num(price.get("output_tokens_per_second")) * _num(output_seconds))
    return tokens_cost(price, tokens_in, tokens_out)


def call_cost(model: dict, *, tokens_in: int | None = None, tokens_out: int | None = None,
              search_requests: int | None = None, video_seconds: float | None = None,
              video_resolution: str | None = None, blocked: bool = False) -> float:
    """Cost of one finished call. A safety block costs $0."""
    if blocked:
        return 0.0
    price = model.get("price") or {}
    if model.get("api") == "veo":
        return round(veo_cost(price, video_seconds, video_resolution), 6)
    if model.get("api") == "omni":
        return round(omni_cost(price, tokens_in, tokens_out, video_seconds), 6)
    return round(tokens_cost(price, tokens_in, tokens_out) + search_cost(price, search_requests), 6)


# ── estimates before the button is pressed ──────────────────────────────────


def _history_average(model_id: str, purpose: str | None, *, limit: int = 20) -> float | None:
    sql = ("SELECT cost_usd FROM ai_calls WHERE model_id = ? AND status = 'success' AND stub = 0")
    params: list = [model_id]
    if purpose:
        sql += " AND purpose = ?"
        params.append(purpose)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = db.fetch_all(sql, params)
    if len(rows) < 3:
        return None
    return sum(r["cost_usd"] or 0 for r in rows) / len(rows)


def estimate_image(model: dict, *, count: int = 1, image_size: str | None = None,
                   input_images: int = 0, purpose: str | None = None) -> float:
    """Pictures: history average for this model, else tokens by size tier."""
    avg = _history_average(model["id"], purpose) or _history_average(model["id"], None)
    if avg is None:
        price = model.get("price") or {}
        tiers = price.get("image_output_tokens") or {}
        tier = image_size or next(iter((model.get("caps") or {}).get("allowed_resolutions") or ["1K"]))
        out_tokens = tiers.get(tier) or DEFAULT_IMAGE_TOKENS.get(tier, 1120)
        in_tokens = TEXT_PROMPT_TOKENS + input_images * IMAGE_INPUT_TOKENS
        avg = tokens_cost(price, in_tokens, out_tokens)
    return round(avg * max(count, 0), 4)


def estimate_text(model: dict, *, purpose: str | None = None, input_images: int = 0,
                  search: bool = False, count: int = 1) -> float:
    avg = _history_average(model["id"], purpose)
    if avg is None:
        price = model.get("price") or {}
        avg = tokens_cost(price, TEXT_PROMPT_TOKENS + input_images * IMAGE_INPUT_TOKENS, TEXT_ANSWER_TOKENS)
        if search:
            avg += search_cost(price, 2)
    return round(avg * max(count, 0), 4)


def estimate_video(model: dict, *, seconds: float, resolution: str = "720p", count: int = 1,
                   input_video_seconds: float = 0) -> float:
    price = model.get("price") or {}
    if model.get("api") == "omni":
        in_tokens = int(_num(price.get("output_tokens_per_second")) * _num(input_video_seconds))
        one = omni_cost(price, in_tokens, None, seconds)
    else:
        one = veo_cost(price, seconds, resolution)
    return round(one * max(count, 0), 4)


def spent_total(since: str | None = None, *, include_stub: bool = False) -> float:
    sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE 1 = 1"
    params: list = []
    if not include_stub:
        sql += " AND stub = 0"
    if since:
        sql += " AND created_at >= ?"
        params.append(since)
    return round(float(db.fetch_value(sql, params, 0.0)), 6)
