"""Files under /data/update: state, settings, operation, history, token, check cache."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

DEFAULT_SETTINGS = {"auto": True, "time": "03:00", "tz": "UTC", "channel": "stable"}

TERMINAL_STATES = ("done", "failed")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text):
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def atomic_write_json(path: str, data, mode: int = 0o644) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        return default


def validate_settings(patch: dict, current: dict) -> dict:
    """Merge a settings patch into current settings. Raises ValueError on bad input."""
    if not isinstance(patch, dict):
        raise ValueError("settings must be an object")
    result = dict(current)
    for key, value in patch.items():
        if key == "auto":
            if not isinstance(value, bool):
                raise ValueError("auto must be true or false")
            result["auto"] = value
        elif key == "time":
            if not isinstance(value, str) or not _TIME_RE.match(value):
                raise ValueError("time must look like HH:MM")
            result["time"] = value
        elif key == "tz":
            if not isinstance(value, str) or not value:
                raise ValueError("tz must be a time zone name")
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(value)
            except Exception:
                raise ValueError(f"unknown time zone: {value}") from None
            result["tz"] = value
        elif key == "channel":
            if value not in ("stable", "beta"):
                raise ValueError("channel must be stable or beta")
            result["channel"] = value
        else:
            raise ValueError(f"unknown setting: {key}")
    return result


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.root = os.path.join(data_dir, "update")
        self.lock = threading.RLock()

    # paths
    def path(self, *parts) -> str:
        return os.path.join(self.root, *parts)

    @property
    def state_path(self):
        return self.path("state.json")

    @property
    def settings_path(self):
        return self.path("settings.json")

    @property
    def op_path(self):
        return self.path("op.json")

    @property
    def history_path(self):
        return self.path("history.jsonl")

    @property
    def token_path(self):
        return self.path("token")

    @property
    def check_path(self):
        return self.path("check.json")

    @property
    def backups_dir(self):
        return os.path.join(self.data_dir, "backups")

    @property
    def db_path(self):
        return os.path.join(self.data_dir, "app.db")

    def stack_dir(self, version: str) -> str:
        return self.path("stacks", version)

    def stack_file(self, version: str) -> str:
        return os.path.join(self.stack_dir(version), "compose.yml")

    def ensure_dirs(self):
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.path("stacks"), exist_ok=True)

    # token
    def ensure_token(self) -> str:
        with self.lock:
            self.ensure_dirs()
            token = self.read_token()
            if token:
                try:
                    os.chmod(self.token_path, 0o600)
                except OSError:
                    pass
                return token
            token = secrets.token_urlsafe(32)
            tmp_path = self.token_path + ".tmp"
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(token + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.token_path)
            return token

    def read_token(self) -> str:
        try:
            with open(self.token_path, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def check_token(self, presented) -> bool:
        expected = self.read_token()
        if not expected or not presented:
            return False
        return hmac.compare_digest(expected.encode(), str(presented).strip().encode())

    # state.json: what is installed
    def read_state(self) -> dict:
        data = read_json(self.state_path, None)
        return data if isinstance(data, dict) else {}

    def write_state(self, **fields) -> dict:
        with self.lock:
            state = self.read_state()
            state.update(fields)
            state["schema"] = 1
            atomic_write_json(self.state_path, state)
            return state

    # settings.json
    def read_settings(self) -> dict:
        data = read_json(self.settings_path, None)
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(data, dict):
            try:
                settings = validate_settings(
                    {k: v for k, v in data.items() if k in DEFAULT_SETTINGS}, settings
                )
            except ValueError:
                pass
        return settings

    def update_settings(self, patch: dict) -> dict:
        with self.lock:
            settings = validate_settings(patch, self.read_settings())
            atomic_write_json(self.settings_path, settings)
            return settings

    # op.json: the current or last update operation
    def read_op(self):
        data = read_json(self.op_path, None)
        return data if isinstance(data, dict) else None

    def write_op(self, op: dict) -> dict:
        with self.lock:
            op = dict(op)
            op["schema"] = 1
            op["updated_at"] = utc_now()
            atomic_write_json(self.op_path, op)
            return op

    def update_op(self, **fields):
        with self.lock:
            op = self.read_op() or {}
            op.update(fields)
            return self.write_op(op)

    def op_log(self, message: str, **fields):
        with self.lock:
            op = self.read_op() or {}
            op.update(fields)
            log = list(op.get("step_log") or [])
            log.append({"at": utc_now(), "state": op.get("state"), "message": message})
            op["step_log"] = log[-200:]
            op["heartbeat_at"] = utc_now()
            return self.write_op(op)

    # check.json: release list cache
    def read_check(self) -> dict:
        data = read_json(self.check_path, None)
        return data if isinstance(data, dict) else {}

    def write_check(self, data: dict):
        with self.lock:
            atomic_write_json(self.check_path, data)

    # history.jsonl
    def append_history(self, record: dict):
        with self.lock:
            self.ensure_dirs()
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            with open(self.history_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    def read_history(self, limit: int = 100) -> list:
        items = []
        try:
            with open(self.history_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        items.reverse()
        return items[:limit]

