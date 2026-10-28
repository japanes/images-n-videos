"""Read side of the jobs page: filtered lists, counts, group load, service health."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from vf.core import db, jobs, settings
from vf.core.errors import AppError
from vf.core.services import render, stt
from vf.modules.jobs_ui import maintenance

# status filter of the page → statuses in the table
STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "all": (),
    "active": jobs.ACTIVE,
    "finished": jobs.FINISHED,
    "problems": ("error", "interrupted"),
    **{s: (s,) for s in (*jobs.ACTIVE, *jobs.FINISHED)},
}

ROW_FIELDS = ("updated_at", "priority")


def _item(row: dict) -> dict:
    out = jobs.summary(row)
    for key in ROW_FIELDS:
        out[key] = row.get(key)
    out["retryable"] = row["status"] in ("error", "interrupted", "cancelled")
    out["cancellable"] = row["status"] in jobs.ACTIVE
    out["known"] = row["kind"] in jobs.handlers()
    return out


def list_page(*, status: str = "all", group: str | None = None, kind: str | None = None,
              ref_type: str | None = None, ref_id: int | None = None, q: str | None = None,
              limit: int = 50, before_id: int | None = None) -> dict:
    if status not in STATUS_FILTERS:
        raise AppError("validation", 422, f"unknown status filter: {status}", field="status")
    where: list[str] = []
    params: list[Any] = []
    statuses = STATUS_FILTERS[status]
    if statuses:
        where.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    if group:
        where.append("group_name = ?")
        params.append(group)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if ref_type:
        where.append("ref_type = ?")
        params.append(ref_type)
    if ref_id is not None:
        where.append("ref_id = ?")
        params.append(ref_id)
    text = (q or "").strip()
    if text:
        # lower() folds ASCII only; other scripts match as typed.
        where.append("(instr(lower(COALESCE(title, '')), lower(?)) > 0 OR instr(lower(kind), lower(?)) > 0"
                     " OR CAST(id AS TEXT) = ?)")
        params.extend([text, text, text])
    if before_id is not None:
        where.append("id < ?")
        params.append(before_id)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit + 1)
    rows = db.fetch_all(sql, params)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [_item(r) for r in rows], "has_more": has_more,
            "next_before_id": rows[-1]["id"] if has_more and rows else None}


def counts() -> dict:
    by_status = {r["status"]: r["n"] for r in db.fetch_all("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}
    out = {s: by_status.get(s, 0) for s in (*jobs.ACTIVE, *jobs.FINISHED)}
    out["active"] = sum(out[s] for s in jobs.ACTIVE)
    out["finished"] = sum(out[s] for s in jobs.FINISHED)
    out["problems"] = out["error"] + out["interrupted"]
    out["all"] = sum(by_status.values())
    return out


def groups() -> list[dict]:
    """Every group with its limit (setting ``jobs.limit.<group>``) and current load."""
    load: dict[str, dict[str, int]] = {}
    for r in db.fetch_all("SELECT group_name, status, COUNT(*) AS n FROM jobs WHERE status IN ('queued','running') "
                          "GROUP BY group_name, status"):
        load.setdefault(r["group_name"], {})[r["status"]] = r["n"]
    names = list(jobs.GROUP_DEFAULTS) + sorted(g for g in load if g not in jobs.GROUP_DEFAULTS)
    out = []
    for name in names:
        limit = settings.get(f"jobs.limit.{name}", jobs.GROUP_DEFAULTS.get(name, 2))
        out.append({"group": name, "limit": int(limit or 1), "setting": f"jobs.limit.{name}",
                    "running": load.get(name, {}).get("running", 0),
                    "queued": load.get(name, {}).get("queued", 0)})
    return out


def kinds() -> list[dict]:
    """Kinds seen in the table plus every registered handler (for the filter)."""
    seen = {r["kind"]: r for r in db.fetch_all(
        "SELECT kind, MAX(group_name) AS group_name, COUNT(*) AS n FROM jobs GROUP BY kind")}
    out = {k: {"kind": k, "group": h.group, "count": 0} for k, h in jobs.handlers().items()}
    for k, r in seen.items():
        out.setdefault(k, {"kind": k, "group": r["group_name"], "count": 0})["count"] = r["n"]
    return sorted(out.values(), key=lambda x: x["kind"])


def backups() -> dict:
    files = maintenance.backup_files()
    last = files[-1] if files else None
    return {
        "count": len(files),
        "last": {"name": last.name, "size": last.stat().st_size,
                 "at": datetime.fromtimestamp(last.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if last else None,
    }


def last_runs() -> dict:
    names = {
        "daily_backup": f"{maintenance.daily_backup.__module__}.{maintenance.daily_backup.__qualname__}",
        "purge_old_jobs": f"{maintenance.purge_old_jobs.__module__}.{maintenance.purge_old_jobs.__qualname__}",
    }
    rows = {r["name"]: r["last_run"] for r in db.fetch_all("SELECT name, last_run FROM scheduler_runs")}
    return {key: rows.get(name) for key, name in names.items()}


def overview() -> dict:
    return {
        "counts": counts(),
        "groups": groups(),
        "kinds": kinds(),
        "runner_alive": jobs.runner.alive(),
        "settings": {k: settings.get(k) for k in (
            "jobs.stuck_minutes", "jobs.keep_days", "jobs.backup_daily", "jobs.backup_keep")},
        "backups": backups(),
        "last_runs": last_runs(),
    }


# ── sibling services ────────────────────────────────────────────────────────

SERVICES = {"render": render, "stt": stt}

# What each service may show on the page besides ok/version (nothing else leaks).
DETAIL_KEYS = {"render": ("ffmpeg", "queue"), "stt": ("busy",)}


async def _one(name: str) -> dict:
    out: dict[str, Any] = {"name": name, "state": "ok", "version": None, "details": {},
                           "error_code": None, "message": None}
    try:
        body = await SERVICES[name].health()
    except AppError as exc:
        out["state"] = "unreachable" if exc.code.endswith("_unavailable") else "problem"
        out["error_code"] = exc.code
        out["message"] = exc.message
        return out
    except Exception as exc:  # noqa: BLE001 — the page must still render
        out.update(state="unreachable", error_code=f"{name}_unavailable", message=str(exc) or type(exc).__name__)
        return out
    if not isinstance(body, dict):
        out.update(state="problem", error_code=f"{name}_failed", message="unexpected health answer")
        return out
    out["version"] = body.get("version")
    out["details"] = {k: body.get(k) for k in DETAIL_KEYS[name] if k in body}
    if body.get("ok") is False:
        out["state"] = "problem"
        out["message"] = body.get("error") if isinstance(body.get("error"), str) else None
    return out


async def health() -> dict:
    results = await asyncio.gather(*(_one(name) for name in SERVICES))
    return {"services": list(results), "checked_at": db.now()}
