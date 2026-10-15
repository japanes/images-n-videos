"""Read-only views over the spend journal (``ai_calls`` + ``ai_call_refs``).

Times in the journal are UTC. The browser sends its offset from UTC in minutes
(``tz``, east positive: Kyiv summer = 180) so that "a day" on the chart and the
period bounds are the user's local days. One offset is used for the whole
period; around a daylight-saving switch a bound can be off by an hour.

Money cards (spent of the credit, remaining) always count real calls only.
Calls made in test mode (``stub = 1``) cost nothing; the table and chart hide
them unless the user turns them on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from vf.core import db, files, pricing, settings
from vf.core.config import get_config
from vf.core.errors import AppError, NotFound
from vf.core.google import credentials, journal
from vf.modules.spend import refs as refs_mod

log = logging.getLogger("vf.spend")

settings.define("spend.credit_usd", 300.0, group="spend", kind="float", min=0, max=100000)
settings.define("spend.credit_days", 90, group="spend", kind="int", min=1, max=3650)

TRIAL_SETTING = "connection.trial_started_on"  # defined by the connection module (01)
KIND_GROUPS = ("image", "video", "text")  # everything else is "other"
FAILED = ("error", "blocked")
MAX_FILL_DAYS = 400
BILLING_URL = "https://console.cloud.google.com/billing/linkedaccount"

_KIND_GROUP_SQL = "CASE WHEN c.kind IN ('image', 'video', 'text') THEN c.kind ELSE 'other' END"

# Light columns for the table; the heavy ones (prompt text, request, response) are in the call card.
LIST_COLUMNS = (
    "id", "created_at", "finished_at", "duration_ms", "attempt", "kind", "purpose", "role", "model_id",
    "region", "prompt_code", "prompt_version", "tokens_in", "tokens_out", "tokens_thinking", "video_seconds",
    "video_resolution", "input_video_seconds", "output_video_seconds", "search_queries", "cost_usd", "status",
    "error_code", "error_text", "http_status", "stub",
)


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    tz: int = 0
    kind: list[str] | None = None
    purpose: list[str] | None = None
    status: list[str] | None = None
    model_id: list[str] | None = None
    include_stub: bool = False
    ref_type: str | None = None
    ref_id: int | None = None


# ---------------------------------------------------------------- helpers

def parse_day(value: Any, *, field: str = "date") -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise AppError("invalid_date", 400, field=field, value=str(value)) from exc


def split_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in str(value).split(",") if v.strip()]
    return items or None


def check_tz(tz: int | None) -> int:
    tz = int(tz or 0)
    if not -840 <= tz <= 840:
        raise AppError("invalid_tz", 400, tz=tz)
    return tz


def utc_bound(day: date, tz: int) -> str:
    """Local midnight of ``day`` as a journal timestamp (UTC, same format as ``db.now()``)."""
    moment = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(minutes=tz)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def local_today(tz: int) -> date:
    return (datetime.now(UTC) + timedelta(minutes=tz)).date()


def _offset_modifier(tz: int) -> str:
    return f"{tz:+d} minutes"


def where(f: Filters) -> tuple[str, list]:
    parts: list[str] = []
    params: list = []
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise AppError("invalid_period", 400, date_from=f.date_from.isoformat(), date_to=f.date_to.isoformat())
    if f.date_from:
        parts.append("c.created_at >= ?")
        params.append(utc_bound(f.date_from, f.tz))
    if f.date_to:
        parts.append("c.created_at < ?")
        params.append(utc_bound(f.date_to + timedelta(days=1), f.tz))
    if f.kind:
        sub = []
        named = [k for k in f.kind if k != "other"]
        if named:
            sub.append(f"c.kind IN ({', '.join('?' * len(named))})")
            params.extend(named)
        if "other" in f.kind:
            sub.append("c.kind NOT IN ('image', 'video', 'text')")
        parts.append("(" + " OR ".join(sub) + ")")
    for column, values in (("purpose", f.purpose), ("status", f.status), ("model_id", f.model_id)):
        if values:
            parts.append(f"c.{column} IN ({', '.join('?' * len(values))})")
            params.extend(values)
    if not f.include_stub:
        parts.append("c.stub = 0")
    if f.ref_type:
        if f.ref_id is None:
            parts.append("EXISTS (SELECT 1 FROM ai_call_refs r WHERE r.call_id = c.id AND r.ref_type = ?)")
            params.append(f.ref_type)
        else:
            parts.append("EXISTS (SELECT 1 FROM ai_call_refs r WHERE r.call_id = c.id "
                         "AND r.ref_type = ? AND r.ref_id = ?)")
            params.extend([f.ref_type, f.ref_id])
    return (" AND ".join(parts) or "1 = 1"), params


def _model_titles() -> dict[str, str]:
    return {r["id"]: r["title"] for r in db.fetch_all("SELECT id, title FROM models")}


def _money(value: Any) -> float:
    return round(float(value or 0), 6)


# ---------------------------------------------------------------- summary

def trial_start() -> date | None:
    raw = settings.get(TRIAL_SETTING)
    try:
        return parse_day(raw, field=TRIAL_SETTING)
    except AppError:
        log.warning("ignoring unreadable trial start date %r", raw)
        return None


def billing_url(project_id: str | None) -> str:
    return f"{BILLING_URL}?project={project_id}" if project_id else BILLING_URL


def _project_id() -> str | None:
    try:
        info = credentials.key_info() or {}
    except Exception:  # the key can vanish between the check and the read
        return None
    return info.get("project_id")


def next_utc_midnight(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    nxt = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
    return nxt.strftime("%Y-%m-%dT%H:%M:%SZ")


def summary(tz: int = 0) -> dict:
    credit = float(settings.get("spend.credit_usd") or 0)
    credit_days = int(settings.get("spend.credit_days") or 0)
    start = trial_start()
    today = local_today(tz)

    spent_all = pricing.spent_total()
    if start:
        spent = pricing.spent_total(utc_bound(start, tz))
        ends = start + timedelta(days=credit_days)
        days_left = max((ends - today).days, 0)
    else:
        spent, ends, days_left = spent_all, None, None

    cap = float(settings.get("google.daily_cap_usd") or 0)
    counts = db.fetch_one(
        "SELECT SUM(stub = 0) AS real_calls, SUM(stub = 1) AS stub_calls, "
        "MAX(CASE WHEN stub = 0 THEN created_at END) AS last_call_at FROM ai_calls") or {}
    project_id = _project_id()
    return {
        "credit_usd": credit,
        "credit_days": credit_days,
        "trial_started_on": start.isoformat() if start else None,
        "trial_ends_on": ends.isoformat() if ends else None,
        "days_left": days_left,
        "expired": bool(ends and today >= ends),
        "today": today.isoformat(),
        "spent_usd": _money(spent),
        "spent_before_trial_usd": _money(spent_all - spent) if start else 0.0,
        "remaining_usd": _money(max(credit - spent, 0)),
        "over_usd": _money(max(spent - credit, 0)),
        "spent_pct": round(spent / credit * 100, 2) if credit > 0 else None,
        "spent_today_usd": journal.spent_today(),
        "daily_cap_usd": cap,
        "cap_resets_at": next_utc_midnight(),
        "real_calls": int(counts.get("real_calls") or 0),
        "stub_calls": int(counts.get("stub_calls") or 0),
        "last_call_at": counts.get("last_call_at"),
        "stub_mode": get_config().stub,
        "project_id": project_id,
        "billing_url": billing_url(project_id),
    }


# ---------------------------------------------------------------- stats (chart + breakdowns)

def _fill_days(f: Filters, found: list[str]) -> list[str]:
    if f.date_from and f.date_to:
        first, last = f.date_from, f.date_to
    elif found:
        first = f.date_from or date.fromisoformat(min(found))
        last = f.date_to or max(date.fromisoformat(max(found)), local_today(f.tz))
    else:
        return []
    span = (last - first).days + 1
    if span <= 0 or span > MAX_FILL_DAYS:
        return sorted(set(found))
    return [(first + timedelta(days=i)).isoformat() for i in range(span)]


def stats(f: Filters) -> dict:
    w, params = where(f)
    total = db.fetch_one(
        f"SELECT COUNT(*) AS calls, COALESCE(SUM(c.cost_usd), 0) AS usd, "
        f"COALESCE(SUM(c.status IN ('error', 'blocked')), 0) AS failed FROM ai_calls c WHERE {w}", params) or {}

    day_rows = db.fetch_all(
        f"SELECT date(c.created_at, ?) AS day, {_KIND_GROUP_SQL} AS grp, COUNT(*) AS calls, "
        f"COALESCE(SUM(c.cost_usd), 0) AS usd FROM ai_calls c WHERE {w} GROUP BY day, grp",
        [_offset_modifier(f.tz), *params])
    by_day: dict[str, dict] = {}
    for r in day_rows:
        d = by_day.setdefault(r["day"], {"day": r["day"], "usd": 0.0, "calls": 0, "by_kind": {}})
        d["usd"] += r["usd"]
        d["calls"] += r["calls"]
        d["by_kind"][r["grp"]] = _money(r["usd"])
    days = []
    for day in _fill_days(f, list(by_day)):
        d = by_day.get(day) or {"day": day, "usd": 0.0, "calls": 0, "by_kind": {}}
        d["usd"] = _money(d["usd"])
        days.append(d)

    def grouped(expr: str) -> list[dict]:
        rows = db.fetch_all(
            f"SELECT {expr} AS key, COUNT(*) AS calls, COALESCE(SUM(c.cost_usd), 0) AS usd, "
            f"COALESCE(SUM(c.status IN ('error', 'blocked')), 0) AS failed "
            f"FROM ai_calls c WHERE {w} GROUP BY key ORDER BY usd DESC, calls DESC", params)
        return [{"key": r["key"], "calls": r["calls"], "usd": _money(r["usd"]), "failed": r["failed"]}
                for r in rows]

    titles = _model_titles()
    by_model = grouped("c.model_id")
    for item in by_model:
        item["title"] = titles.get(item["key"]) if item["key"] else None

    return {
        "total": {"calls": int(total.get("calls") or 0), "usd": _money(total.get("usd")),
                  "failed": int(total.get("failed") or 0)},
        "days": days,
        "by_kind": grouped(_KIND_GROUP_SQL),
        "by_model": by_model,
        "by_purpose": grouped("c.purpose"),
    }


# ---------------------------------------------------------------- the table

def list_calls(f: Filters, *, limit: int = 50, offset: int = 0) -> dict:
    w, params = where(f)
    head = db.fetch_one(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(c.cost_usd), 0) AS usd FROM ai_calls c WHERE {w}", params) or {}
    cols = ", ".join(f"c.{c}" for c in LIST_COLUMNS)
    rows = db.fetch_all(
        f"SELECT {cols} FROM ai_calls c WHERE {w} ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset])
    refs_by_call: dict[int, list[dict]] = {}
    if rows:
        ids = [r["id"] for r in rows]
        for r in db.fetch_all(
                f"SELECT call_id, ref_type, ref_id FROM ai_call_refs WHERE call_id IN ({', '.join('?' * len(ids))}) "
                "ORDER BY ref_type, ref_id", ids):
            refs_by_call.setdefault(r["call_id"], []).append({"type": r["ref_type"], "id": r["ref_id"]})
    titles = _model_titles()
    items = []
    for r in rows:
        r["stub"] = bool(r["stub"])
        r["model_title"] = titles.get(r["model_id"]) if r["model_id"] else None
        r["refs"] = refs_by_call.get(r["id"], [])
        items.append(r)
    return {"items": items, "total": int(head.get("n") or 0), "sum_usd": _money(head.get("usd")),
            "limit": limit, "offset": offset}


# ---------------------------------------------------------------- one call

def _attachment(a: Any) -> dict:
    if not isinstance(a, dict):
        return {"mime": None, "size": None, "sha256": None, "file_id": None, "exists": False}
    out = {k: a.get(k) for k in ("mime", "size", "sha256", "file_id")}
    out.update(exists=False, kind=None, url=None, thumb_url=None, title=None)
    file_id = a.get("file_id")
    if file_id:
        row = db.get("files", int(file_id))
        if row:
            out.update(exists=True, kind=row["kind"], url=files.url(row["id"]),
                       title=row.get("title") or row.get("original_name"),
                       thumb_url=files.url(row["id"], w=160) if (row["kind"] == "image" or row.get("poster_path"))
                       else None)
    return out


def get_call(call_id: int) -> dict:
    row = journal.get_call(call_id)
    if row is None:
        raise NotFound("call", id=call_id)
    row["stub"] = bool(row["stub"])
    row["model_title"] = _model_titles().get(row["model_id"]) if row.get("model_id") else None
    row["refs"] = [refs_mod.resolve(r["type"], r["id"]) for r in row.get("refs") or []]
    attachments = row.get("attachments_json")
    row["attachments"] = [_attachment(a) for a in attachments] if isinstance(attachments, list) else []
    return row


# ---------------------------------------------------------------- cost of one object

def cost_of(ref_type: str, ref_id: int) -> dict:
    row = db.fetch_one(
        "SELECT COUNT(*) AS calls, "
        "COALESCE(SUM(CASE WHEN c.stub = 0 THEN c.cost_usd END), 0) AS usd, "
        "COALESCE(SUM(CASE WHEN c.stub = 1 THEN c.cost_usd END), 0) AS stub_usd, "
        "COALESCE(SUM(c.stub = 1), 0) AS stub_calls, "
        "COALESCE(SUM(c.status IN ('error', 'blocked')), 0) AS failed, "
        "COALESCE(SUM(c.status = 'running'), 0) AS running "
        "FROM ai_calls c JOIN ai_call_refs r ON r.call_id = c.id WHERE r.ref_type = ? AND r.ref_id = ?",
        (ref_type, ref_id)) or {}
    return {"ref_type": ref_type, "ref_id": ref_id, "calls": int(row.get("calls") or 0),
            "usd": _money(row.get("usd")), "stub_usd": _money(row.get("stub_usd")),
            "stub_calls": int(row.get("stub_calls") or 0), "failed": int(row.get("failed") or 0),
            "running": int(row.get("running") or 0)}


# ---------------------------------------------------------------- filter choices

def filter_choices() -> dict:
    def distinct(column: str) -> list[str]:
        return [r["v"] for r in db.fetch_all(
            f"SELECT DISTINCT {column} AS v FROM ai_calls WHERE {column} IS NOT NULL ORDER BY v")]

    titles = _model_titles()
    return {
        "kinds": distinct("kind"),
        "purposes": distinct("purpose"),
        "statuses": distinct("status"),
        "models": [{"id": m, "title": titles.get(m)} for m in distinct("model_id")],
        "ref_types": [r["v"] for r in db.fetch_all("SELECT DISTINCT ref_type AS v FROM ai_call_refs ORDER BY v")],
    }
