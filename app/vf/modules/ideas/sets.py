"""Idea sets: storage, the view the browser gets, and the chat card kept in step.

A set is one press of «Ideas» in a chat. Its card is a chat message of kind
``ideas.concept`` whose ``data`` is the view of the set: every change of the set
rewrites the card (``sync``), so a reloaded page shows the same thing.
"""

from __future__ import annotations

import logging
from typing import Any

from vf.core import db, files, jobs
from vf.core.errors import AppError, NotFound
from vf.core.google import journal
from vf.modules.ideas import common as C

log = logging.getLogger("vf.ideas")

IMAGE_FIELDS = ("n", "title", "prompt", "edited", "work_id", "frame_id", "message_id", "drawn_at")


def set_row(set_id: Any) -> dict:
    try:
        row = db.get("ideas_sets", int(set_id))
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise NotFound("ideas_set", id=set_id)
    return row


def create(chat_id: int, *, brief: dict, scene: dict, research: bool, options: dict) -> int:
    from vf.modules.ideas import brief as B

    now = db.now()
    return db.insert("ideas_sets", {
        "chat_id": chat_id, "brief_json": brief, "files_json": B.file_ids(brief), "scene_json": scene,
        "research": 1 if research else 0, "options_json": options, "images_json": [], "status": "running",
        "created_at": now, "updated_at": now,
    })


def update(set_id: int, values: dict) -> None:
    values = dict(values)
    if values.get("error"):
        values["error"] = str(values["error"])[:4000]
    values["updated_at"] = db.now()
    db.update("ideas_sets", set_id, values)


def image(row: dict, n: Any) -> dict:
    """One card of the set by its number (1-based)."""
    try:
        number = int(n)
    except (TypeError, ValueError):
        number = 0
    for item in row.get("images_json") or []:
        if int(item.get("n") or 0) == number:
            return item
    raise AppError("ideas_card_unknown", 404, "The set has no such card", n=n)


def put_image(set_id: int, item: dict) -> None:
    """Save one card (matched by ``n``) back into the set."""
    row = set_row(set_id)
    images = [item if int(i.get("n") or 0) == int(item["n"]) else i for i in row.get("images_json") or []]
    update(set_id, {"images_json": images})


# ── the view ────────────────────────────────────────────────────────────────

def _file(file_id: Any) -> dict | None:
    try:
        return files.public(files.get(int(file_id)))
    except (NotFound, TypeError, ValueError):
        return None


def _pictures(brief: dict) -> list[dict]:
    out = []
    for role, key in (("product", "product_refs"), ("visual", "visual_refs")):
        for file_id in brief.get(key) or []:
            out.append({"file_id": file_id, "role": role, "file": _file(file_id)})
    return out


def _research(row: dict) -> dict | None:
    if not row.get("research"):
        return None
    found = row.get("research_json") or {}
    return {"summary": found.get("summary") or "", "sources": found.get("sources") or [],
            "cached": bool(found.get("cached")), "created_at": found.get("created_at"),
            "error_code": found.get("error_code"), "error": found.get("error"),
            "cost_usd": round(float(found.get("cost_usd") or 0), 6), "model_id": found.get("model_id"),
            "niche": found.get("niche") or "", "platform": found.get("platform") or "",
            "done": bool(found)}


def _image_view(item: dict) -> dict:
    return {k: item.get(k) for k in IMAGE_FIELDS} | {"edited": bool(item.get("edited"))}


def view(row: dict) -> dict:
    options = row.get("options_json") or {}
    concept = row.get("concept_json") or None
    return {
        "id": row["id"], "chat_id": row.get("chat_id"), "message_id": row.get("message_id"),
        "job_id": row.get("job_id"), "status": row["status"], "error_code": row.get("error_code"),
        "error": row.get("error"), "brief": row.get("brief_json") or {}, "pictures": _pictures(row.get("brief_json") or {}),
        "scene": row.get("scene_json") or {}, "research": _research(row),
        "concept": {"name": concept.get("name") or "", "direction": concept.get("direction") or ""} if concept else None,
        "images": [_image_view(i) for i in row.get("images_json") or []],
        "options": {"draw_first": bool(options.get("draw_first")),
                    "product_to_frames": bool(options.get("product_to_frames"))},
        "draw_error_code": options.get("draw_error_code"), "draw_error": options.get("draw_error"),
        "cost_usd": round(float(row.get("cost_usd") or 0), 6), "model_id": row.get("model_id"),
        "prompt": {"code": C.PROMPT_IDEAS, "version": row.get("prompt_version")} if row.get("prompt_version") else None,
        "spend_link": f"/settings/spend?ref_type={C.REF_SET}&ref_id={row['id']}&period=all",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def card_text(row: dict) -> str:
    """The line the chat shows for the card (list previews, replies)."""
    concept = row.get("concept_json") or {}
    return concept.get("name") or (row.get("brief_json") or {}).get("niche") or ""


def refresh_cost(set_id: int) -> float:
    """The set's own spend from the journal (research, ideas, new ideas for one card)."""
    cost = journal.cost_of(C.REF_SET, set_id)
    update(set_id, {"cost_usd": cost})
    return cost


def sync(set_id: int) -> dict:
    """Rewrite the chat card from the set; returns the set's view."""
    row = set_row(set_id)
    out = view(row)
    if row.get("message_id"):
        from vf.modules import chat

        try:
            chat.update_posted(int(row["message_id"]), text=card_text(row), data=out, status=row["status"],
                               cost_usd=float(row.get("cost_usd") or 0), error_code=row.get("error_code"),
                               error=row.get("error"))
        except NotFound:
            log.warning("ideas set %s: its chat message %s is gone", set_id, row["message_id"])
    return out


# ── sets left "running" ─────────────────────────────────────────────────────

def _job(job_id: Any) -> dict | None:
    return db.get("jobs", int(job_id)) if job_id else None


def settle(row: dict) -> dict:
    """A set still "running" whose job is over or gone is put in order (and its card with it)."""
    if row["status"] != "running":
        return row
    job = _job(row.get("job_id"))
    if job is not None and job["status"] in jobs.ACTIVE:
        return row
    if job is None:
        status, code, error = "error", "interrupted", None
    elif job["status"] == "cancelled":
        status, code, error = "cancelled", "cancelled", None
    elif job["status"] == "done":
        status, code, error = ("done", None, None) if row.get("concept_json") else ("error", "ideas_empty", None)
    else:
        status, code, error = "error", job.get("error_code") or "interrupted", job.get("error")
    update(row["id"], {"status": status, "error_code": code, "error": error})
    refresh_cost(row["id"])
    sync(row["id"])
    return set_row(row["id"])


def sweep() -> int:
    """At start: a set whose job did not survive the stop of the app is closed with ``interrupted``.

    Runs before the job runner starts, so only a queued job is still alive."""
    count = 0
    for row in db.fetch_all("SELECT * FROM ideas_sets WHERE status = 'running'"):
        job = _job(row.get("job_id"))
        if job is not None and job["status"] == "queued":
            continue
        update(row["id"], {"status": "error", "error_code": "interrupted", "error": None})
        refresh_cost(row["id"])
        sync(row["id"])
        count += 1
    return count


def get(set_id: Any) -> dict:
    return view(settle(set_row(set_id)))


__all__ = ["card_text", "create", "get", "image", "put_image", "refresh_cost", "set_row", "settle", "sweep",
           "sync", "update", "view"]
