"""Google failures, sorted into codes the interface can explain in plain words.

``classify(exc)`` turns whatever the SDK, google-auth or the network raised
into a ``GoogleCallError``. The original text from Google is kept verbatim in
``raw`` and goes to the spend journal unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from vf.core.errors import AppError

# Finish reasons that mean "Google declined the content": sending the same
# request again would be declined again, and the call is not billed.
BLOCKED_FINISH_REASONS = frozenset({
    "SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION",
    "IMAGE_PROHIBITED_CONTENT",
})

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_KEYWORDS = (
    "resource_exhausted", "rate_limit", "quota", "unavailable", "deadline_exceeded", "internal",
    "overloaded", "transport", "connection", "unreachable", "timed out", "timeout",
    "name resolution", "broken pipe",
)
RATE_LIMIT_KEYWORDS = ("resource_exhausted", "rate_limit", "ratelimit", "quota", "too many requests")

# code -> HTTP status for the API answer
_STATUS = {
    "no_key": 409,
    "billing_disabled": 402,
    "api_disabled": 412,
    "permission_denied": 403,
    "model_not_found": 404,
    "rate_limited": 429,
    "invalid_grant": 401,
    "safety_blocked": 422,
    "refused": 422,
    "timeout": 504,
    "network": 503,
    "bad_request": 400,
    "server_error": 502,
    "cancelled": 499,
    "daily_cap": 429,
    "unknown": 502,
}


class GoogleCallError(AppError):
    """A Google call that did not give a usable answer."""

    def __init__(self, code: str, raw: str = "", *, http_status: int | None = None,
                 retryable: bool = False, retry_after: float | None = None, blocked: bool = False,
                 call_ids: list[int] | None = None, **details: Any):
        super().__init__(code, _STATUS.get(code, 502), raw[:500] or code.replace("_", " "),
                         google_status=http_status, **details)
        self.raw = raw
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after
        self.blocked = blocked
        self.call_ids = list(call_ids or [])

    def to_dict(self) -> dict:
        body = super().to_dict()
        body["details"] = {**body["details"], "google_message": self.raw[:2000], "call_ids": self.call_ids}
        return body


def retry_after_of(text: str) -> float | None:
    """API-suggested cooldown: ``retryDelay: '17s'`` or ``Retry-After: 30``."""
    for pattern in (r"retry[\-_ ]?after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)",
                    r"retrydelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s?"):
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _status_of(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def raw_text(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    if type(exc).__name__ not in text:
        text = f"{type(exc).__name__}: {text}"
    return text


def classify(exc: BaseException) -> GoogleCallError:
    if isinstance(exc, GoogleCallError):
        return exc
    raw = raw_text(exc)
    low = raw.lower()
    status = _status_of(exc)
    name = type(exc).__name__.lower()

    rate = status == 429 or any(k in low for k in RATE_LIMIT_KEYWORDS)
    if rate:
        return GoogleCallError("rate_limited", raw, http_status=status, retryable=True,
                               retry_after=retry_after_of(raw))
    if "invalid_grant" in low or "invalid jwt" in low or "account not found" in low:
        return GoogleCallError("invalid_grant", raw, http_status=status)
    if "billing" in low and ("disabled" in low or "not been enabled" in low or "enable billing" in low):
        return GoogleCallError("billing_disabled", raw, http_status=status)
    if ("has not been used" in low or "is disabled" in low or "service_disabled" in low) and "api" in low:
        return GoogleCallError("api_disabled", raw, http_status=status)
    if status == 404 or ("not found" in low and "model" in low) or "publisher model" in low:
        return GoogleCallError("model_not_found", raw, http_status=status)
    if status == 403 or "permission_denied" in low or "permission denied" in low:
        return GoogleCallError("permission_denied", raw, http_status=status)
    if "timeout" in name or "timed out" in low or "deadline_exceeded" in low or status == 504:
        return GoogleCallError("timeout", raw, http_status=status, retryable=True)
    if status in RETRYABLE_STATUS:
        return GoogleCallError("server_error", raw, http_status=status, retryable=True)
    if any(k in low for k in RETRYABLE_KEYWORDS) or "connect" in name or "transport" in name:
        return GoogleCallError("network", raw, http_status=status, retryable=True)
    if status == 400 or "invalid_argument" in low:
        return GoogleCallError("bad_request", raw, http_status=status)
    return GoogleCallError("unknown", raw, http_status=status)


def enum_name(value: Any) -> str:
    """Bare name of an SDK enum in whatever shape the SDK hands it over."""
    if value is None:
        return ""
    name = str(getattr(value, "name", value) or "").strip()
    return name.rsplit(".", 1)[-1].upper()


def refusal_detail(response: Any) -> tuple[str, bool]:
    """Why an answer holds nothing usable, in words, and whether it is a block."""
    bits: list[str] = []
    blocked = False
    feedback = getattr(response, "prompt_feedback", None)
    reason = enum_name(getattr(feedback, "block_reason", None))
    if reason and reason != "BLOCKED_REASON_UNSPECIFIED":
        blocked = True
        note = getattr(feedback, "block_reason_message", None)
        bits.append(f"prompt blocked ({reason}" + (f": {note}" if note else "") + ")")
    candidates = getattr(response, "candidates", None) or []
    first = candidates[0] if candidates else None
    finish = enum_name(getattr(first, "finish_reason", None))
    if finish and finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        blocked = blocked or finish in BLOCKED_FINISH_REASONS
        note = getattr(first, "finish_message", None)
        bits.append(f"finish_reason={finish}" + (f" ({note})" if note else ""))
    categories = [
        enum_name(getattr(r, "category", None))
        for r in (getattr(first, "safety_ratings", None) or [])
        if getattr(r, "blocked", False)
    ]
    if any(categories):
        blocked = True
        bits.append("safety: " + ", ".join(c for c in categories if c))
    said = " ".join(
        (getattr(p, "text", "") or "").strip()
        for p in (getattr(getattr(first, "content", None), "parts", None) or [])
        if not getattr(p, "thought", False)
    ).strip()
    if said:
        bits.append(f"model said: {said[:300]}")
    return "; ".join(bits), blocked
