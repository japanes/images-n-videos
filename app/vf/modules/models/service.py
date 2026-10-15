"""Models, roles and general settings (module 02).

The registry itself lives in the core (``vf.core.models_registry``); this
module adds what the "Models" and "Settings" screens need on top of it:

* the availability check: one free listing of Google's publisher models,
  matched against the registry (``check_availability``), and a way to forget
  its marks (``reset_availability``);
* a checked edit of the user's own price for a model (``set_price``);
* the effective model of every kind (what a call really uses right now);
* the general settings shared by the creative modules (variants per run,
  attachments, default text language, output sizes per aspect ratio).

No model id appears here: everything comes from the registry data.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from vf.core import db, events, google, models_registry, settings
from vf.core.errors import AppError

log = logging.getLogger("vf.models")

# The region the availability check lists models in (the connection check of
# module 01 uses the same one).
CHECK_REGION = "us-central1"
CHECK_PURPOSE = "models_check"

# ── general settings (the "General" group of the settings screen) ──────────

TEXT_LANGUAGES = ["ru", "uk", "en"]

# Output size in pixels for each aspect ratio the creative screens offer.
DEFAULT_ASPECT_SIZES: dict[str, list[int]] = {
    "1:1": [1080, 1080],
    "4:5": [1080, 1350],
    "9:16": [1080, 1920],
    "3:4": [1080, 1440],
}
MIN_SIDE = 64
MAX_SIDE = 8192

settings.define("general.text_language", "en", group="general", kind="enum", choices=TEXT_LANGUAGES)
settings.define("general.variants", 3, group="general", kind="int", min=1, max=8)
settings.define("general.max_attachments", 10, group="general", kind="int", min=1, max=14)
settings.define("general.aspect_sizes", DEFAULT_ASPECT_SIZES, group="general", kind="json",
                widget="aspect_sizes")


def _side(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    side = int(value)
    return side if MIN_SIDE <= side <= MAX_SIDE else None


def aspect_sizes() -> dict[str, tuple[int, int]]:
    """The output size of every known aspect ratio, as ``{"4:5": (1080, 1350)}``.

    The stored value is a JSON setting; anything broken in it falls back to the
    default size of that aspect ratio instead of failing a generation.
    """
    stored = settings.get("general.aspect_sizes")
    stored = stored if isinstance(stored, dict) else {}
    out: dict[str, tuple[int, int]] = {}
    for aspect, default in DEFAULT_ASPECT_SIZES.items():
        raw = stored.get(aspect)
        w = h = None
        if isinstance(raw, list | tuple) and len(raw) == 2:
            w, h = _side(raw[0]), _side(raw[1])
        out[aspect] = (w, h) if w and h else (default[0], default[1])
    return out


def output_size(aspect: str | None) -> tuple[int, int] | None:
    """Output size for one aspect ratio; ``None`` when the ratio is not configured."""
    if not aspect:
        return None
    return aspect_sizes().get(aspect)


# ── availability ────────────────────────────────────────────────────────────

_VERSION_TAIL = re.compile(r"-\d{3}$")


def _norm(name: str) -> str:
    """``publishers/google/models/x-001@002`` -> ``x-001``."""
    name = str(name or "").strip().lower().rsplit("/", 1)[-1]
    return name.split("@", 1)[0]


def _matches(model_id: str, names: set[str]) -> bool:
    """Exact id, or the same id with/without a ``-NNN`` version tail."""
    mid = _norm(model_id)
    if mid in names:
        return True
    bare = _VERSION_TAIL.sub("", mid)
    return any(_VERSION_TAIL.sub("", n) == bare for n in names)


def last_checked_at() -> str | None:
    return db.fetch_value("SELECT MAX(available_checked_at) FROM models WHERE removed_from_seed = 0")


async def check_availability(*, region: str = CHECK_REGION, purpose: str = CHECK_PURPOSE) -> dict:
    """List Google's models visible to the project (free) and mark the registry.

    If the listing is empty or none of the registry models is in it, the result
    is treated as inconclusive and nothing is marked: a wrong "not available"
    would silently move the defaults to other models.
    """
    listed = await google.list_models(region=region, purpose=purpose)
    names = {_norm(item.get("name") or "") for item in listed if item.get("name")}
    names.discard("")
    models = models_registry.list_models()
    found = {m["id"]: _matches(m["id"], names) for m in models}
    conclusive = bool(names) and any(found.values())
    if conclusive:
        models_registry.set_availability(found)
    else:
        log.warning("model availability check was inconclusive (%d names listed, none matched)", len(names))
    return {
        "checked": conclusive,
        "region": region,
        "listed": len(names),
        "checked_at": last_checked_at(),
        "items": [{"id": mid, "available": ok} for mid, ok in found.items()] if conclusive else [],
    }


def reset_availability() -> None:
    """Forget the marks of the last check (all models count as "not checked")."""
    db.execute("UPDATE models SET available = NULL, available_checked_at = NULL")
    events.publish("models.changed", {"availability": "reset"})


# ── the user's own price ────────────────────────────────────────────────────

# Money fields of a registry price that the user may override (USD).
MONEY_FIELDS = ("input_per_1m", "output_per_1m", "search_per_request")
TABLE_FIELDS = ("per_second",)  # {resolution: USD per second}
MAX_PRICE = 10_000.0


def _money(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise AppError("bad_price", 400, field=field)
    value = float(value)
    if value < 0 or value > MAX_PRICE:
        raise AppError("bad_price", 400, field=field)
    return value


def clean_price(model: dict, price: dict | None) -> dict | None:
    """Check a user price against the registry price of the model.

    Only money fields the registry price has can be overridden. Values equal
    to the registry price are dropped, so the override keeps only real changes;
    an empty result means "use the registry price".
    """
    if price is None:
        return None
    if not isinstance(price, dict):
        raise AppError("bad_price", 400)
    seed = model.get("seed_price") or {}
    out: dict[str, Any] = {}
    for key, value in price.items():
        if key in MONEY_FIELDS and key in seed:
            amount = _money(value, key)
            if amount != seed.get(key):
                out[key] = amount
        elif key in TABLE_FIELDS and isinstance(seed.get(key), dict):
            if not isinstance(value, dict):
                raise AppError("bad_price", 400, field=key)
            table = {}
            for res, amount in value.items():
                if res not in seed[key]:
                    raise AppError("bad_price", 400, field=f"{key}.{res}")
                amount = _money(amount, f"{key}.{res}")
                if amount != seed[key][res]:
                    table[res] = amount
            if table:
                out[key] = table
        else:
            raise AppError("bad_price", 400, field=str(key))
    return out or None


def set_price(model_id: str, price: dict | None) -> dict:
    model = models_registry.get(model_id)
    return models_registry.set_user_price(model_id, clean_price(model, price))


# ── what is really used ─────────────────────────────────────────────────────


def effective_defaults() -> dict[str, str | None]:
    """The model a call of each kind uses when nothing else is chosen."""
    out: dict[str, str | None] = {}
    for kind in models_registry.KINDS:
        try:
            out[kind] = models_registry.default_for(kind)["id"]
        except AppError:
            out[kind] = None
    return out


def overview() -> dict:
    return {
        "effective": effective_defaults(),
        "checked_at": last_checked_at(),
        "check_region": CHECK_REGION,
    }
