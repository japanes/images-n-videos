"""The user's service-account key: stored on the data volume, never sent to the browser.

The key file lives at ``<data>/secrets/google-sa.json`` with mode 0600. Only
``key_info()`` (project, account e-mail, last characters of the key id) ever
leaves this module.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vf.core import events
from vf.core.config import get_config
from vf.core.errors import AppError

KEY_NAME = "google-sa.json"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
REQUIRED_FIELDS = ("type", "project_id", "private_key", "client_email")

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "creds": None, "info": None}
_listeners: list = []


def on_change(fn) -> None:
    """Called (no arguments) after the key is saved or deleted."""
    _listeners.append(fn)


def key_path() -> Path:
    return get_config().secrets_dir / KEY_NAME


def has_key() -> bool:
    return key_path().is_file()


def parse_key(raw: bytes | str) -> dict:
    """Validate the uploaded JSON. Raises ``AppError("key_invalid")`` with a reason."""
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        info = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise AppError("key_invalid", 400, reason="not_json") from exc
    if not isinstance(info, dict):
        raise AppError("key_invalid", 400, reason="not_json")
    missing = [f for f in REQUIRED_FIELDS if not info.get(f)]
    if missing:
        raise AppError("key_invalid", 400, reason="missing_fields", fields=missing)
    if info.get("type") != "service_account":
        raise AppError("key_invalid", 400, reason="not_service_account", type=str(info.get("type")))
    if "BEGIN PRIVATE KEY" not in str(info.get("private_key")):
        raise AppError("key_invalid", 400, reason="bad_private_key")
    return info


def save_key(raw: bytes | str) -> dict:
    info = parse_key(raw)
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(info, fh)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    _reset()
    events.publish("google.key_changed", {"present": True})
    return key_info() or {}


def delete_key() -> None:
    path = key_path()
    if path.exists():
        path.unlink()
    _reset()
    events.publish("google.key_changed", {"present": False})


def _reset() -> None:
    with _lock:
        _cache.update(mtime=None, creds=None, info=None)
    for fn in list(_listeners):
        fn()


def _read_info() -> dict:
    path = key_path()
    if not path.is_file():
        raise AppError("no_key", 409)
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["info"] is not None and _cache["mtime"] == mtime:
            return _cache["info"]
        info = json.loads(path.read_text(encoding="utf-8"))
        _cache.update(mtime=mtime, info=info, creds=None)
        return info


def key_info() -> dict | None:
    """Safe facts about the key for the interface. No secret material."""
    if not has_key():
        return None
    try:
        info = _read_info()
    except (OSError, ValueError):
        return {"present": True, "readable": False}
    key_id = str(info.get("private_key_id") or "")
    stat = key_path().stat()
    return {
        "present": True,
        "readable": True,
        "project_id": info.get("project_id"),
        "client_email": info.get("client_email"),
        "key_id_tail": key_id[-6:] if key_id else None,
        "saved_at": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def project_id() -> str:
    return str(_read_info()["project_id"])


def fingerprint() -> str:
    """Changes whenever the key file changes (used to rebuild clients)."""
    path = key_path()
    return f"{path.stat().st_mtime_ns}" if path.is_file() else "none"


def load_credentials():
    """google-auth credentials for the stored key (cached until the file changes)."""
    from google.oauth2 import service_account

    info = _read_info()
    with _lock:
        if _cache["creds"] is None:
            _cache["creds"] = service_account.Credentials.from_service_account_info(info, scopes=list(SCOPES))
        return _cache["creds"]
