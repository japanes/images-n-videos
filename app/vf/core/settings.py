"""Key/value settings with declared defaults.

Modules declare their settings at import time::

    settings.define("studio.variants", 3, group="general", kind="int", min=1, max=8)

Values live in the ``settings`` table as JSON; an absent row means "default".
Only declared keys can be read or written through the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vf.core import db, events
from vf.core.errors import AppError


@dataclass
class SettingDef:
    key: str
    default: Any
    group: str = "general"
    kind: str = "any"  # int | float | bool | str | enum | json | any
    choices: list | None = None
    min: float | None = None
    max: float | None = None
    public: bool = True  # exposed to the browser
    meta: dict = field(default_factory=dict)


_defs: dict[str, SettingDef] = {}


def define(key: str, default: Any, *, group: str = "general", kind: str | None = None,
           choices: list | None = None, min: float | None = None, max: float | None = None,
           public: bool = True, **meta: Any) -> SettingDef:
    if kind is None:
        kind = _guess_kind(default)
    d = SettingDef(key, default, group, kind, choices, min, max, public, meta)
    _defs[key] = d
    return d


def _guess_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return "json"


def definitions() -> dict[str, SettingDef]:
    return dict(_defs)


def get(key: str, default: Any = None) -> Any:
    row = db.fetch_one("SELECT value_json FROM settings WHERE key = ?", (key,))
    if row is not None:
        return row["value_json"]
    d = _defs.get(key)
    if d is not None:
        return d.default
    return default


def get_many(prefix: str) -> dict[str, Any]:
    out = {k: d.default for k, d in _defs.items() if k.startswith(prefix)}
    for row in db.fetch_all("SELECT key, value_json FROM settings WHERE key LIKE ?", (prefix + "%",)):
        out[row["key"]] = row["value_json"]
    return out


def set(key: str, value: Any, *, validate: bool = True) -> Any:  # noqa: A001
    d = _defs.get(key)
    if validate:
        if d is None:
            raise AppError("unknown_setting", 400, key=key)
        value = _coerce(d, value)
    db.execute(
        "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        (key, _dump(value), db.now()),
    )
    events.publish("settings.changed", {"key": key, "value": value if (d is None or d.public) else None})
    return value


def reset(key: str) -> None:
    db.execute("DELETE FROM settings WHERE key = ?", (key,))
    events.publish("settings.changed", {"key": key})


def public_values() -> dict[str, Any]:
    stored = {r["key"]: r["value_json"] for r in db.fetch_all("SELECT key, value_json FROM settings")}
    return {k: stored.get(k, d.default) for k, d in _defs.items() if d.public}


def describe() -> list[dict]:
    stored = {r["key"]: r["value_json"] for r in db.fetch_all("SELECT key, value_json FROM settings")}
    return [
        {"key": d.key, "group": d.group, "kind": d.kind, "default": d.default,
         "value": stored.get(d.key, d.default), "choices": d.choices, "min": d.min, "max": d.max,
         "meta": d.meta}
        for d in _defs.values() if d.public
    ]


def _dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _coerce(d: SettingDef, value: Any) -> Any:
    try:
        if d.kind == "bool":
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on")
            value = bool(value)
        elif d.kind == "int":
            value = int(value)
        elif d.kind == "float":
            value = float(value)
        elif d.kind == "str":
            value = "" if value is None else str(value)
    except (TypeError, ValueError) as exc:
        raise AppError("invalid_setting", 400, key=d.key) from exc
    if d.choices is not None and value not in d.choices:
        raise AppError("invalid_setting", 400, key=d.key, choices=d.choices)
    if d.kind in ("int", "float"):
        if d.min is not None and value < d.min:
            raise AppError("invalid_setting", 400, key=d.key, min=d.min)
        if d.max is not None and value > d.max:
            raise AppError("invalid_setting", 400, key=d.key, max=d.max)
    return value
