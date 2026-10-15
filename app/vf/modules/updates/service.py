"""What the updater says, cleaned for the browser, plus the app's own side of it.

Only known fields pass, long texts are cut, container paths are reduced to file
names. The page never sees the updater token or its address.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from vf.core import jobs
from vf.core.config import get_config
from vf.core.errors import AppError
from vf.core.services import updater

VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
TIME_RE = re.compile(TIME_PATTERN)
CHANNELS = ("stable", "beta")

# Errors meaning "the updater cannot be asked right now": the page shows a calm note
# and the rest of the app keeps working.
UNREACHABLE = ("updater_unavailable", "updater_failed")

VERSION_LIMIT = 64
SHORT_LIMIT = 64
TEXT_LIMIT = 2000
NOTES_LIMIT = 50_000
RELEASES_LIMIT = 30
STEP_LOG_LIMIT = 50
BUSY_LIMIT = 50
HISTORY_LIMIT = 100


# ── small cleaners ──────────────────────────────────────────────────────────

def _text(value: Any, limit: int = TEXT_LIMIT) -> str | None:
    if value is None or isinstance(value, dict | list):
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:limit] or None


def _version(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= VERSION_LIMIT else None


def _link(value: Any) -> str | None:
    if isinstance(value, str) and len(value) <= TEXT_LIMIT and value.startswith(("https://", "http://")):
        return value
    return None


def _file_name(value: Any) -> str | None:
    """Backup path inside the updater container -> just the file name."""
    if not isinstance(value, str) or not value:
        return None
    return posixpath.basename(value.replace("\\", "/"))[:SHORT_LIMIT * 2] or None


def _busy(items: Any) -> list[dict]:
    if not isinstance(items, list):
        return []
    return [
        {"kind": _text(b.get("kind"), SHORT_LIMIT) or "", "title": _text(b.get("title"), 200) or ""}
        for b in items if isinstance(b, dict)
    ][:BUSY_LIMIT]


def is_version(value: str) -> bool:
    return len(value) <= VERSION_LIMIT and bool(VERSION_RE.match(value))


# ── updater answers ─────────────────────────────────────────────────────────

def clean_release(rel: Any) -> dict | None:
    if not isinstance(rel, dict):
        return None
    version = _version(rel.get("version"))
    if not version:
        return None
    return {
        "version": version,
        "prerelease": bool(rel.get("prerelease")),
        "published_at": _text(rel.get("published_at"), SHORT_LIMIT),
        "notes_md": _text(rel.get("notes_md"), NOTES_LIMIT) or "",
        "html_url": _link(rel.get("html_url")),
        "installable": bool(rel.get("installable")),
        "min_upgrade_from": _version(rel.get("min_upgrade_from")),
        "failed_before": bool(rel.get("failed_before")),
    }


def clean_operation(op: Any) -> dict | None:
    if not isinstance(op, dict):
        return None
    return {
        "id": _text(op.get("id"), SHORT_LIMIT),
        "kind": _text(op.get("kind"), SHORT_LIMIT),
        "purpose": _text(op.get("purpose"), SHORT_LIMIT),
        "source": _text(op.get("source"), SHORT_LIMIT),
        "from": _version(op.get("from")),
        "to": _version(op.get("to")),
        "force": bool(op.get("force")),
        "state": _text(op.get("state"), SHORT_LIMIT),
        "active": bool(op.get("active")),
        "result": _text(op.get("result"), SHORT_LIMIT),
        "started_at": _text(op.get("started_at"), SHORT_LIMIT),
        "finished_at": _text(op.get("finished_at"), SHORT_LIMIT),
        "error": _text(op.get("error")),
        "backup_file": _file_name(op.get("backup_file")),
        "busy": _busy(op.get("busy")),
    }


def clean_status(raw: dict) -> dict:
    available = [r for r in map(clean_release, raw.get("available") or []) if r][:RELEASES_LIMIT]
    steps = raw.get("step_log") if isinstance(raw.get("step_log"), list) else []
    step_log = [
        {"at": _text(s.get("at"), SHORT_LIMIT), "state": _text(s.get("state"), SHORT_LIMIT),
         "message": _text(s.get("message")) or ""}
        for s in steps if isinstance(s, dict)
    ][-STEP_LOG_LIMIT:]
    channel = raw.get("channel")
    time_value = raw.get("time")
    return {
        "current_version": _version(raw.get("current_version")),
        "installed_version": _version(raw.get("installed_version")),
        "channel": channel if channel in CHANNELS else "stable",
        "auto": raw.get("auto") is True,
        "time": time_value if isinstance(time_value, str) and TIME_RE.match(time_value) else None,
        "tz": _text(raw.get("tz"), SHORT_LIMIT),
        "dev": raw.get("dev") is True,
        "last_check_at": _text(raw.get("last_check_at"), SHORT_LIMIT),
        "last_check_error": _text(raw.get("last_check_error")),
        "available": available,
        "state": _text(raw.get("state"), SHORT_LIMIT) or "idle",
        "step_log": step_log,
        "error": _text(raw.get("error")),
        "operation": clean_operation(raw.get("operation")),
    }


def clean_history_item(item: dict) -> dict:
    return {
        "op_id": _text(item.get("op_id"), SHORT_LIMIT),
        "kind": _text(item.get("kind"), SHORT_LIMIT),
        "source": _text(item.get("source"), SHORT_LIMIT),
        "version_from": _version(item.get("version_from")),
        "version_to": _version(item.get("version_to")),
        "started_at": _text(item.get("started_at"), SHORT_LIMIT),
        "finished_at": _text(item.get("finished_at"), SHORT_LIMIT),
        "result": _text(item.get("result"), SHORT_LIMIT),
        "error": _text(item.get("error")),
        "backup_file": _file_name(item.get("backup_file")),
    }


def newest_version(status: dict) -> str | None:
    """Version the header notice offers: the newest one that can be installed directly,
    otherwise simply the newest one (the page explains why it cannot be installed)."""
    available = status.get("available") or []
    pick = next((r for r in available if r["installable"]), available[0] if available else None)
    return pick["version"] if pick else None


# ── what the page gets ──────────────────────────────────────────────────────

def _app_side() -> dict:
    running = [{"kind": j.get("kind") or "", "title": j.get("title") or j.get("kind") or ""}
               for j in jobs.running_jobs()][:BUSY_LIMIT]
    return {"app_version": get_config().version, "jobs_paused": jobs.runner.paused, "running_jobs": running}


def unreachable(exc: AppError) -> dict:
    return {**_app_side(), "reachable": False, "reason": exc.code, "message": exc.message[:500],
            "updater": None, "newest": None}


def overview_from(raw: dict) -> dict:
    status = clean_status(raw)
    return {**_app_side(), "reachable": True, "reason": None, "message": None,
            "updater": status, "newest": newest_version(status)}


async def overview() -> dict:
    try:
        raw = await updater.status()
    except AppError as exc:
        if exc.code in UNREACHABLE:
            return unreachable(exc)
        raise
    return overview_from(raw)


async def check() -> dict:
    return overview_from(await updater.check())


async def install(version: str, force: bool) -> dict:
    version = version.strip()
    if not is_version(version):
        raise AppError("update_bad_request", 400, "version must look like 1.2.3")
    body = await updater.install(version, force=force)
    return {"ok": True, "operation": clean_operation(body.get("operation"))}


async def save_settings(values: dict) -> dict:
    values = {k: v for k, v in values.items() if v is not None}
    if not values:
        raise AppError("update_bad_request", 400, "nothing to change")
    return overview_from(await updater.save_settings(values))


async def stop() -> dict:
    await updater.stop()
    return {"ok": True}


async def history() -> dict:
    items = await updater.history()
    return {"items": [clean_history_item(i) for i in items[:HISTORY_LIMIT]]}
