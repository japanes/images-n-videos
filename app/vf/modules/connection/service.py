"""Google connection (module 01): upload the key, check it, show what works.

The key file itself is handled by ``vf.core.google.credentials`` (stored with
mode 0600, never sent to the browser). This module adds:

- stricter validation of the uploaded file with plain reasons
  (OAuth client file, truncated JSON, missing ``private_key_id`` ...);
- the ``google_credentials`` row: safe facts about the key and the result of
  the last check;
- the checks themselves, in order: access token → list of models →
  short text call; plus the optional paid ones: test picture and Omni;
- the user's marks: trial start date and "I restored the key ban".

Every check that reaches Google is written to the spend journal with purpose
``connection_check`` (the core gateway does the journaling).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from vf.core import db, events, files, models_registry, prompts, settings
from vf.core.config import get_config
from vf.core.errors import AppError
from vf.core.google import credentials, token
from vf.modules.models import service as models_service

log = logging.getLogger("vf.connection")

PURPOSE = "connection_check"
MAX_KEY_BYTES = 64 * 1024
# Spec: the free model list is asked in us-central1 (the region Veo needs).
LIST_REGION = "us-central1"
TEXT_PROMPT = "connection.check_text"
IMAGE_PROMPT = "connection.check_image"
REQUIRED_FIELDS = ("project_id", "client_email", "private_key", "private_key_id")
# Errors that make every later check pointless: stop the chain on them.
BLOCKING = frozenset({"no_key", "key_invalid", "invalid_grant", "billing_disabled", "api_disabled",
                      "permission_denied"})
CHECKS = ("token", "models", "text", "image", "omni")

TRIAL_SETTING = "connection.trial_started_on"
BAN_SETTING = "connection.key_ban_restored"
TRIAL_DAYS_SETTING = "spend.credit_days"  # defined by module 03; 90 if absent

# Read by module 03 (spend log) through settings.get: "YYYY-MM-DD" or None.
# Not public: edited only on /connection (PUT /api/connection checks the date).
settings.define(TRIAL_SETTING, None, group="connection", kind="str", public=False)
# True once the user says the JSON-key ban is back (or there was none):
# the wizard and the connection screen stop reminding. Reset for a new key.
settings.define(BAN_SETTING, False, group="connection", kind="bool", public=False)

_check_lock = asyncio.Lock()
OmniCheck = Callable[[dict], Awaitable[dict | None]]
_omni_check: dict[str, OmniCheck | None] = {"fn": None}


def register_omni_check(fn: OmniCheck) -> None:
    """The video module plugs in a live Omni request here.

    ``fn(model)`` must make the cheapest real Omni call (journaled with
    purpose ``connection_check``) and raise ``GoogleCallError`` on failure.
    It may return ``{"cost_usd": ..., "file_id": ...}``.
    """
    _omni_check["fn"] = fn


def omni_check_available() -> bool:
    return _omni_check["fn"] is not None


# ── key upload ─────────────────────────────────────────────────────────────

def validate_key(raw: bytes) -> dict:
    """Check an uploaded file before it is stored. Raises ``AppError("key_invalid")``
    with ``reason`` the interface turns into a plain sentence. Never echoes values."""
    if len(raw) > MAX_KEY_BYTES:
        raise AppError("key_invalid", 400, reason="too_large", max_bytes=MAX_KEY_BYTES)
    if not raw.strip():
        raise AppError("key_invalid", 400, reason="empty")
    try:
        info = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        # A cut-off download lands here too.
        raise AppError("key_invalid", 400, reason="not_json") from None
    if not isinstance(info, dict):
        raise AppError("key_invalid", 400, reason="not_json")
    if "installed" in info or "web" in info:
        raise AppError("key_invalid", 400, reason="oauth_client")
    kind = info.get("type")
    if kind != "service_account":
        raise AppError("key_invalid", 400, reason="not_service_account",
                       type=kind if isinstance(kind, str) and len(kind) < 40 else None)
    missing = [f for f in REQUIRED_FIELDS if not info.get(f)]
    if missing:
        raise AppError("key_invalid", 400, reason="missing_fields", fields=missing)
    # Last word on the format belongs to the core (bad private key, ...).
    credentials.parse_key(raw)
    return info


def save_key(raw: bytes) -> dict:
    info = validate_key(raw)
    credentials.save_key(raw)
    with db.tx():
        db.execute("DELETE FROM google_credentials")
        db.insert("google_credentials", {
            "project_id": str(info["project_id"]),
            "client_email": str(info["client_email"]),
            "private_key_id": str(info["private_key_id"]),
            "uploaded_at": db.now(),
        })
    _key_changed()
    log.info("Google key saved for project %s", info["project_id"])
    return state()


def delete_key() -> dict:
    credentials.delete_key()
    db.execute("DELETE FROM google_credentials")
    _key_changed()
    log.info("Google key deleted")
    return state()


def _key_changed() -> None:
    """A new key may mean a new project: forget what the old one could do."""
    settings.set(BAN_SETTING, False)
    stale = {m["id"]: None for m in models_registry.list_models(include_removed=True)
             if m["available"] is not None}
    if stale:
        models_registry.set_availability(stale)  # type: ignore[arg-type]  # None = not checked
    _publish()


def _publish() -> None:
    events.publish("connection.updated", {"present": credentials.has_key()})


# ── the stored row ─────────────────────────────────────────────────────────

def _row() -> dict | None:
    """The row for the key on disk. Re-created if the file was put there by hand."""
    info = credentials.key_info()
    row = db.fetch_one("SELECT * FROM google_credentials ORDER BY id DESC LIMIT 1")
    if info is None:
        if row is not None:
            db.execute("DELETE FROM google_credentials")
        return None
    if not info.get("readable"):
        return row
    tail = info.get("key_id_tail")
    if row is not None and row["project_id"] == info.get("project_id") \
            and row["client_email"] == info.get("client_email") \
            and (row.get("private_key_id") or "")[-6:] == (tail or ""):
        return row
    with db.tx():
        db.execute("DELETE FROM google_credentials")
        db.insert("google_credentials", {
            "project_id": str(info.get("project_id") or ""),
            "client_email": str(info.get("client_email") or ""),
            "private_key_id": None,
            "uploaded_at": info.get("saved_at") or db.now(),
        })
    return db.fetch_one("SELECT * FROM google_credentials ORDER BY id DESC LIMIT 1")


def _results(row: dict | None) -> dict:
    res = (row or {}).get("last_check_result_json")
    return res if isinstance(res, dict) else {}


def _store(name: str, result: dict) -> None:
    row = _row()
    if row is None:
        return
    results = _results(row)
    results[name] = result
    db.update("google_credentials", row["id"], {"last_check_at": result["at"],
                                                "last_check_result_json": results})


def _forget_project_errors() -> None:
    """Before a new run: drop picture/Omni failures that were caused by the project
    (billing, API, role, key). They would keep a red tick after the fix."""
    row = _row()
    results = _results(row)
    stale = [name for name in ("image", "omni")
             if ((results.get(name) or {}).get("error") or {}).get("code") in BLOCKING]
    if row is not None and stale:
        for name in stale:
            results.pop(name, None)
        db.update("google_credentials", row["id"], {"last_check_result_json": results})


def _ok(**extra: Any) -> dict:
    return {"status": "ok", "at": db.now(), **{k: v for k, v in extra.items() if v is not None}}


def _failed(err: AppError, **extra: Any) -> dict:
    raw = getattr(err, "raw", None) or err.message or ""
    return {
        "status": "error", "at": db.now(),
        "error": {"code": err.code, "google_message": str(raw)[:2000],
                  "http_status": getattr(err, "http_status", None),
                  "call_ids": list(getattr(err, "call_ids", []) or [])},
        **{k: v for k, v in extra.items() if v is not None},
    }


def _skipped() -> dict:
    return {"status": "skipped", "at": db.now()}


# ── models for each capability ─────────────────────────────────────────────

def _pick(kind: str, api: str | None = None) -> dict | None:
    """The model the app would use for a capability (default first, enabled only)."""
    if api is None:
        try:
            return models_registry.default_for(kind)
        except AppError:
            return None
    pool = [m for m in models_registry.list_models(kind, enabled_only=True) if m["api"] == api]
    pool.sort(key=lambda m: (not m["is_default"], m["available"] is False))
    return pool[0] if pool else None


def capability_models() -> dict[str, dict | None]:
    return {
        "images": _pick("image"),
        "text": _pick("text"),
        "veo": _pick("video", "veo"),
        "omni": _pick("video", "omni"),
    }


def _mark(model: dict | None, ok: bool) -> None:
    if model:
        models_registry.set_availability({model["id"]: ok})


# ── checks ─────────────────────────────────────────────────────────────────

def _require_key() -> None:
    if not credentials.has_key():
        raise AppError("no_key", 409)


def _busy() -> AppError:
    return AppError("check_running", 409)


async def run_basic_checks() -> dict:
    """Checks 1–3: token, list of models, short text call. Stops at a blocking error."""
    _require_key()
    if _check_lock.locked():
        raise _busy()
    async with _check_lock:
        _forget_project_errors()
        stop = False

        # 1. access token
        try:
            await token.check_token(purpose=PURPOSE)
            _store("token", _ok())
        except AppError as err:
            _store("token", _failed(err))
            stop = True

        # 2. list of models (free)
        if stop:
            _store("models", _skipped())
        else:
            try:
                # Module 02 owns the availability marks: it lists (free, journaled)
                # and marks the registry, unless the answer is inconclusive.
                listing = await models_service.check_availability(region=LIST_REGION, purpose=PURPOSE)
                seen = sorted(i["id"] for i in listing["items"] if i["available"])
                _store("models", _ok(count=listing["listed"], seen=seen, region=LIST_REGION,
                                     conclusive=bool(listing["checked"])))
            except AppError as err:
                _store("models", _failed(err, region=LIST_REGION))
                stop = err.code in BLOCKING

        # 3. short text call (paid, fractions of a cent)
        model = _pick("text")
        if stop:
            _store("text", _skipped())
        else:
            try:
                res = await prompts.run_prompt(TEXT_PROMPT, purpose=PURPOSE, thinking_level="low")
                _mark(models_registry.find(res.model_id), True)
                _store("text", _ok(model_id=res.model_id, cost_usd=res.cost_usd, call_ids=res.call_ids))
            except AppError as err:
                if err.code == "model_not_found":
                    _mark(model, False)
                _store("text", _failed(err, model_id=model["id"] if model else None))
    _publish()
    return state()


async def run_image_check() -> dict:
    """Check 5: draw one test picture with the default image model (paid)."""
    _require_key()
    if _check_lock.locked():
        raise _busy()
    model = _pick("image")
    async with _check_lock:
        try:
            res = await prompts.run_prompt(IMAGE_PROMPT, purpose=PURPOSE)
            data, mime = res.images[0]
            saved = files.save_bytes(data, mime=mime, name="connection-test", origin="generated",
                                     title="Connection test", source_type=PURPOSE)
            _mark(models_registry.find(res.model_id), True)
            _store("image", _ok(model_id=res.model_id, cost_usd=res.cost_usd, call_ids=res.call_ids,
                                file_id=saved["id"]))
        except AppError as err:
            if err.code == "model_not_found":
                _mark(model, False)
            _store("image", _failed(err, model_id=model["id"] if model else None))
    _publish()
    return state()


async def run_omni_check() -> dict:
    """Check 4: Omni answers only to a live request; the video module supplies it."""
    _require_key()
    fn = _omni_check["fn"]
    if fn is None:
        raise AppError("check_unavailable", 409, check="omni")
    model = _pick("video", "omni")
    if model is None:
        raise AppError("no_model", 409, kind="omni")
    if _check_lock.locked():
        raise _busy()
    async with _check_lock:
        try:
            extra = await fn(model) or {}
            _mark(model, True)
            _store("omni", _ok(model_id=model["id"], cost_usd=extra.get("cost_usd"),
                               file_id=extra.get("file_id")))
        except AppError as err:
            if err.code == "model_not_found":
                _mark(model, False)
            _store("omni", _failed(err, model_id=model["id"]))
    _publish()
    return state()


# ── what the screen shows ──────────────────────────────────────────────────

def _blocking_error(results: dict) -> str | None:
    for name in ("token", "models", "text"):
        res = results.get(name) or {}
        code = (res.get("error") or {}).get("code")
        if res.get("status") == "error" and code in BLOCKING:
            return code
    return None


def _capability(cap: str, model: dict | None, results: dict) -> dict:
    """State of one tick: ok (a live call worked), seen (in Google's list, not tried),
    not_listed, error (its own live call failed), blocked (an error above stops
    everything), unknown (not checked yet), no_model (nothing enabled)."""
    out: dict[str, Any] = {"id": cap, "model_id": model["id"] if model else None,
                           "model_title": model["title"] if model else None,
                           "region": model["region"] if model else None, "state": "unknown", "via": None}
    if model is None:
        out["state"] = "no_model"
        return out
    out["preview"] = bool(model.get("preview"))
    if cap == "omni":
        # The live check asks for the shortest clip the model allows: the price button needs it.
        durations = [d for d in (model.get("caps") or {}).get("allowed_durations") or [] if isinstance(d, int | float)]
        out["check_seconds"] = min(durations) if durations else None
    live = {"images": "image", "text": "text", "omni": "omni"}.get(cap)
    res = results.get(live) if live else None
    mine = bool(res) and res.get("model_id") in (None, model["id"])
    if mine and res.get("status") == "error":
        out.update(state="error", via="live", at=res.get("at"), error=res.get("error"))
        return out
    blocking = _blocking_error(results)
    if blocking:
        out.update(state="blocked", blocked_by=blocking)
        return out
    if mine and res.get("status") == "ok":
        out.update(state="ok", via="live", at=res.get("at"))
        return out
    if cap == "omni":
        return out  # only a live request tells
    text = results.get("text") or {}
    listing = results.get("models") or {}
    if text.get("status") == "ok" and listing.get("status") == "ok" and listing.get("conclusive", True):
        seen = model["id"] in (listing.get("seen") or [])
        out.update(state="seen" if seen else "not_listed", via="list", at=listing.get("at"))
    return out


def _trial() -> dict:
    raw = settings.get(TRIAL_SETTING)
    start = parse_day(raw) if raw else None
    if start is None:
        return {"started_on": None, "ends_on": None, "days_left": None}
    try:
        days = int(settings.get(TRIAL_DAYS_SETTING, 90) or 90)
    except (TypeError, ValueError):
        days = 90
    ends = start + timedelta(days=days)
    today = datetime.now(UTC).date()
    return {"started_on": start.isoformat(), "ends_on": ends.isoformat(),
            "days_left": max(0, (ends - today).days)}


def parse_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def state() -> dict:
    """Everything the connection screen needs. No secret material."""
    row = _row()
    info = credentials.key_info()
    results = _results(row)
    models = capability_models()
    key = None
    if info is not None:
        key = {
            "readable": bool(info.get("readable")),
            "project_id": info.get("project_id"),
            "client_email": info.get("client_email"),
            "key_id_tail": info.get("key_id_tail"),
            "uploaded_at": (row or {}).get("uploaded_at") or info.get("saved_at"),
        }
    image = results.get("image") or {}
    test_file = None
    if image.get("status") == "ok" and image.get("file_id"):
        try:
            test_file = files.public(files.get(int(image["file_id"])))
        except AppError:
            test_file = None
    return {
        "key": key,
        "stub": get_config().stub,
        "last_check_at": (row or {}).get("last_check_at"),
        "checks": {name: results.get(name) for name in CHECKS},
        "capabilities": [_capability(cap, models[cap], results) for cap in ("images", "text", "veo", "omni")],
        "test_image": test_file,
        "omni_check_available": omni_check_available(),
        "list_region": LIST_REGION,
        "trial": _trial(),
        "key_ban_restored": bool(settings.get(BAN_SETTING)),
        "max_key_bytes": MAX_KEY_BYTES,
    }


def update_marks(body: dict) -> dict:
    """Trial start date and the key-ban mark."""
    if "trial_started_on" in body:
        raw = body["trial_started_on"]
        if raw in (None, ""):
            settings.reset(TRIAL_SETTING)
        else:
            day = parse_day(raw) if isinstance(raw, str) and len(raw) == 10 else None
            today = datetime.now(UTC).date()
            if day is None or day > today + timedelta(days=1) or day < today - timedelta(days=3650):
                raise AppError("validation", 400, field="trial_started_on")
            settings.set(TRIAL_SETTING, day.isoformat())
    if "key_ban_restored" in body:
        settings.set(BAN_SETTING, bool(body["key_ban_restored"]))
    _publish()
    return state()


__all__ = [
    "MAX_KEY_BYTES", "delete_key", "omni_check_available", "register_omni_check",
    "run_basic_checks", "run_image_check", "run_omni_check", "save_key", "state", "update_marks",
    "validate_key",
]
