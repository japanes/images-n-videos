"""The model registry: which Google models exist, what they cost, what they can do.

Model ids live only in ``seeds/models.json``. The seed is loaded into the
``models`` table at startup; the user's own edits (enabled, default, own price)
live in separate columns and survive re-seeding.

Roles are the jobs that need a text model (describe a photo, find objects...).
Each role takes the default text model unless the user overrides it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vf.core import db, events
from vf.core.errors import AppError

SEED_PATH = Path(__file__).resolve().parents[2] / "seeds" / "models.json"

KINDS = ("image", "video", "text")

# role -> what the model must be able to do (keys of the text model "caps").
ROLES: dict[str, list[str]] = {
    "vision_describe": ["accepts_images", "json_mode"],
    "image_regions": ["accepts_images", "json_mode"],
    "text_placement": ["accepts_images", "json_mode"],
    "shot_ideas": ["accepts_images", "json_mode"],
    "research": ["search"],
    "video_brief": ["accepts_images", "json_mode"],
    "image_text": ["json_mode"],
    "prompt_enhance": ["accepts_images"],
}


def register_role(role: str, needs: list[str]) -> None:
    """Modules may add roles of their own."""
    ROLES[role] = list(needs)


# ── seeding ─────────────────────────────────────────────────────────────────


def load_seed(path: Path | None = None) -> dict:
    return json.loads((path or SEED_PATH).read_text(encoding="utf-8"))


def seed(data: dict | None = None) -> dict:
    """Upsert the seed into the table. Returns counts {added, updated, removed}."""
    data = data or load_seed()
    stamp = db.now()
    seen: list[str] = []
    added = updated = 0
    with db.tx():
        for sort, rec in enumerate(data.get("models") or []):
            model_id = str(rec["id"])
            if rec.get("kind") not in KINDS:
                raise ValueError(f"model {model_id}: bad kind {rec.get('kind')!r}")
            seen.append(model_id)
            row = db.fetch_one("SELECT id, user_touched_default FROM models WHERE id = ?", (model_id,))
            values = {
                "kind": rec["kind"],
                "title": rec.get("title") or model_id,
                "region": rec.get("region") or "global",
                "api": rec.get("api") or "generate_content",
                "sort": sort,
                "seed_json": rec,
                "removed_from_seed": 0,
                "updated_at": stamp,
            }
            if row is None:
                db.insert("models", {"id": model_id, **values, "enabled": 1, "is_default": 0})
                added += 1
            else:
                db.update_where("models", "id = ?", (model_id,), values)
                updated += 1
        if seen:
            marks = ",".join("?" for _ in seen)
            removed = db.execute(
                f"UPDATE models SET removed_from_seed = 1, updated_at = ? WHERE id NOT IN ({marks})",
                (stamp, *seen),
            ).rowcount
        else:
            removed = 0
        # Defaults follow the seed for every kind the user has not chosen by hand.
        for kind in KINDS:
            touched = db.fetch_value(
                "SELECT COUNT(*) FROM models WHERE kind = ? AND user_touched_default = 1 "
                "AND is_default = 1 AND removed_from_seed = 0", (kind,), 0,
            )
            if touched:
                continue
            seed_default = next(
                (str(r["id"]) for r in data.get("models") or [] if r.get("kind") == kind and r.get("default")),
                None,
            )
            db.execute("UPDATE models SET is_default = 0 WHERE kind = ?", (kind,))
            if seed_default:
                db.execute("UPDATE models SET is_default = 1 WHERE id = ?", (seed_default,))
    return {"added": added, "updated": updated, "removed": removed}


# ── reading ─────────────────────────────────────────────────────────────────


def _public(row: dict) -> dict:
    seed_rec = row.get("seed_json") or {}
    seed_price = seed_rec.get("price") or {}
    user_price = row.get("user_price_json") or None
    price = _merge(seed_price, user_price or {})
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "region": row["region"],
        "api": row["api"],
        "preview": bool(seed_rec.get("preview")),
        "enabled": bool(row["enabled"]),
        "is_default": bool(row["is_default"]),
        "available": None if row["available"] is None else bool(row["available"]),
        "available_checked_at": row.get("available_checked_at"),
        "removed": bool(row["removed_from_seed"]),
        "price": price,
        "seed_price": seed_price,
        "user_price": user_price,
        "caps": seed_rec.get("caps") or {},
    }


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def list_models(kind: str | None = None, *, enabled_only: bool = False,
                include_removed: bool = False) -> list[dict]:
    sql = "SELECT * FROM models WHERE 1 = 1"
    params: list[Any] = []
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if enabled_only:
        sql += " AND enabled = 1"
    if not include_removed:
        sql += " AND removed_from_seed = 0"
    sql += " ORDER BY kind, sort, id"
    return [_public(r) for r in db.fetch_all(sql, params)]


def find(model_id: str) -> dict | None:
    row = db.fetch_one("SELECT * FROM models WHERE id = ?", (model_id,))
    return _public(row) if row else None


def get(model_id: str) -> dict:
    model = find(model_id)
    if model is None:
        raise AppError("model_unknown", 404, model_id=model_id)
    return model


def default_for(kind: str) -> dict:
    """The default model of a kind; falls back to the first usable one."""
    rows = list_models(kind, enabled_only=True)
    usable = [m for m in rows if m["available"] is not False]
    for pool in (usable, rows):
        for m in pool:
            if m["is_default"]:
                return m
        if pool:
            return pool[0]
    raise AppError("no_model", 409, kind=kind)


def resolve(kind: str, model_id: str | None = None) -> dict:
    """The model to call: the one asked for (checked) or the default of the kind."""
    if not model_id:
        return default_for(kind)
    model = get(model_id)
    if model["kind"] != kind:
        raise AppError("model_wrong_kind", 400, model_id=model_id, kind=kind)
    if not model["enabled"]:
        raise AppError("model_disabled", 409, model_id=model_id)
    return model


def suits_role(model: dict, role: str) -> bool:
    caps = model.get("caps") or {}
    return model["kind"] == "text" and all(caps.get(need) for need in ROLES.get(role, []))


def model_for_role(role: str) -> dict:
    if role not in ROLES:
        raise AppError("role_unknown", 400, role=role)
    row = db.fetch_one("SELECT model_id FROM role_models WHERE role = ?", (role,))
    if row:
        model = find(row["model_id"])
        if model and model["enabled"] and not model["removed"]:
            if not suits_role(model, role):
                raise AppError("role_model_unsuitable", 409, role=role, model_id=model["id"])
            return model
    model = default_for("text")
    if not suits_role(model, role):
        raise AppError("role_model_unsuitable", 409, role=role, model_id=model["id"])
    return model


def roles_overview() -> list[dict]:
    overrides = {r["role"]: r["model_id"] for r in db.fetch_all("SELECT role, model_id FROM role_models")}
    texts = list_models("text", enabled_only=True)
    out = []
    for role, needs in ROLES.items():
        try:
            effective = model_for_role(role)["id"]
        except AppError:
            effective = None
        out.append({
            "role": role,
            "needs": needs,
            "override": overrides.get(role),
            "model_id": effective,
            "candidates": [m["id"] for m in texts if suits_role(m, role)],
        })
    return out


# ── user edits ──────────────────────────────────────────────────────────────


def set_enabled(model_id: str, enabled: bool) -> dict:
    model = get(model_id)
    if not enabled and model["is_default"]:
        raise AppError("model_is_default", 409, model_id=model_id)
    db.update_where("models", "id = ?", (model_id,), {"enabled": enabled, "updated_at": db.now()})
    return _changed(model_id)


def set_default(model_id: str) -> dict:
    model = get(model_id)
    with db.tx():
        db.execute("UPDATE models SET is_default = 0, user_touched_default = 0 WHERE kind = ?",
                   (model["kind"],))
        db.update_where("models", "id = ?", (model_id,),
                        {"is_default": 1, "user_touched_default": 1, "enabled": 1, "updated_at": db.now()})
    return _changed(model_id)


def set_user_price(model_id: str, price: dict | None) -> dict:
    get(model_id)
    if price is not None and not isinstance(price, dict):
        raise AppError("bad_price", 400)
    db.update_where("models", "id = ?", (model_id,),
                    {"user_price_json": price or None, "updated_at": db.now()})
    return _changed(model_id)


def set_role_model(role: str, model_id: str | None) -> None:
    if role not in ROLES:
        raise AppError("role_unknown", 400, role=role)
    if model_id is None:
        db.execute("DELETE FROM role_models WHERE role = ?", (role,))
    else:
        model = get(model_id)
        if not suits_role(model, role):
            raise AppError("role_model_unsuitable", 400, role=role, model_id=model_id)
        db.insert("role_models", {"role": role, "model_id": model_id, "updated_at": db.now()},
                  or_replace=True)
    events.publish("models.changed", {"role": role})


def set_availability(found: dict[str, bool]) -> None:
    """Record which models the connection check saw in the user's project."""
    stamp = db.now()
    with db.tx():
        for model_id, ok in found.items():
            db.update_where("models", "id = ?", (model_id,),
                            {"available": ok, "available_checked_at": stamp})
    events.publish("models.changed", {})


def _changed(model_id: str) -> dict:
    events.publish("models.changed", {"model_id": model_id})
    return get(model_id)


# ── video capabilities ──────────────────────────────────────────────────────


def video_resolutions(model: dict) -> dict[str, list[int]]:
    """``"720p,1080p@8,4k@8"`` -> ``{"720p": [4, 6, 8], "1080p": [8], "4k": [8]}``."""
    caps = model.get("caps") or {}
    durations = sorted(int(d) for d in caps.get("allowed_durations") or [])
    cap = caps.get("max_duration_seconds")
    if cap:
        durations = [d for d in durations if d <= int(cap)]
    raw = caps.get("allowed_resolutions") or "720p"
    items = raw if isinstance(raw, list) else str(raw).split(",")
    table: dict[str, list[int]] = {}
    for item in items:
        name, _, tail = str(item).strip().partition("@")
        name = name.strip().lower()
        if not name:
            continue
        only = [int(p) for p in tail.split("|") if p.strip().isdigit()]
        limited = [d for d in durations if d in only] if only else list(durations)
        table[name] = limited or list(durations)
    return table


def check_video_request(model: dict, seconds: int, resolution: str, aspect: str | None = None) -> None:
    table = video_resolutions(model)
    res = resolution.lower()
    if res not in table:
        raise AppError("video_resolution_unsupported", 400, model_id=model["id"], resolution=resolution,
                       allowed=list(table))
    if int(seconds) not in table[res]:
        raise AppError("video_duration_unsupported", 400, model_id=model["id"], seconds=seconds,
                       allowed=table[res])
    aspects = (model.get("caps") or {}).get("allowed_aspects") or ["9:16", "16:9"]
    if aspect and aspect not in aspects:
        raise AppError("video_aspect_unsupported", 400, model_id=model["id"], aspect=aspect, allowed=aspects)
