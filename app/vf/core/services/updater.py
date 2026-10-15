"""Client of the ``updater`` container. It shares a token with the app through
``/data/update/token``; every call except health carries it."""

from __future__ import annotations

import hmac
from typing import Any

from vf.core.config import get_config
from vf.core.errors import AppError
from vf.core.services._http import call

# The updater answers errors as {"ok": false, "error": <code>, "message": <text>}.
# These statuses are read as answers so its own code and words reach the UI.
_ERROR_STATUSES = (400, 401, 403, 404, 405, 409, 500)

# 409 "conflict" texts of the updater (updater/vf_updater/engine.py) -> app error code.
_CONFLICTS = (
    ("developer mode", "updates_dev_mode", 409),
    ("already running", "update_busy", 409),
    ("an update is running", "update_busy", 409),
    ("is not newer than", "update_not_newer", 409),
    ("switch to the beta channel", "update_needs_beta", 409),
    ("cannot check releases", "update_check_failed", 502),
)


def token() -> str | None:
    path = get_config().data_dir / "update" / "token"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def check_token(value: str | None) -> None:
    expected = token()
    if not expected or not value or not hmac.compare_digest(value, expected):
        raise AppError("forbidden", 403, "bad updater token")


def _headers() -> dict:
    t = token()
    if not t:
        raise AppError("updater_unavailable", 503, "updater token is missing")
    return {"X-VF-Token": t}


def _url(path: str) -> str:
    return get_config().updater_url + path


async def health() -> dict:
    return await call("updater", "GET", _url("/health"), timeout=5)


def error_from(body: dict) -> AppError:
    """AppError for an updater error answer, keeping the updater's message."""
    code = str(body.get("error") or "")
    message = str(body.get("message") or code or "updater error")[:2000]
    if code == "conflict":
        for needle, app_code, status in _CONFLICTS:
            if needle in message:
                return AppError(app_code, status, message)
        return AppError("update_conflict", 409, message)
    if code == "not_found" and message.startswith("release "):
        return AppError("update_not_found", 404, message)
    if code == "bad_request":
        return AppError("update_bad_request", 400, message)
    if code in ("unauthorized", "forbidden"):
        return AppError("updater_unavailable", 503, "the updater did not accept the app token")
    return AppError("updater_failed", 502, message, service_code=code or None)


async def _request(method: str, path: str, *, json: Any = None, timeout: float = 10.0) -> Any:
    body = await call("updater", method, _url(path), json=json, headers=_headers(), timeout=timeout,
                      ok_statuses=_ERROR_STATUSES)
    if isinstance(body, dict) and body.get("ok") is False and "error" in body:
        raise error_from(body)
    if not isinstance(body, dict):
        raise AppError("updater_failed", 502, "unexpected answer from the updater")
    return body


async def status() -> dict:
    return await _request("GET", "/status")


async def check() -> dict:
    return await _request("POST", "/check", json={}, timeout=60)


async def install(version: str, force: bool = False) -> dict:
    return await _request("POST", "/install", json={"version": version, "force": force}, timeout=30)


async def save_settings(values: dict) -> dict:
    return await _request("POST", "/settings", json=values)


async def stop() -> dict:
    return await _request("POST", "/stop", json={})


async def history() -> list[dict]:
    """Install and rollback records, newest first. The updater answers {"items": [...]}."""
    body = await _request("GET", "/history")
    items = body.get("items")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
