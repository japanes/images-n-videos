"""Messages of a chat: storage, the view, and keeping results up to date.

A result message points at studio frames or video clips (``data_json.items``).
While something is being made, each read looks at the job, the frame or the
clip and saves what it finds; a finished item keeps its own picture or video
(later edits of the same frame do not change an older message). So a page
reloaded in the middle of a generation shows the same placeholders and then
the results, nothing is lost.
"""

from __future__ import annotations

from typing import Any

from vf.core import db, files
from vf.core.errors import AppError, NotFound
from vf.modules.chat import store

ACTIVE = ("queued", "running")
FINAL = ("done", "error", "cancelled")
REF_TYPES = ("frame", "work", "video_run", "video_clip", "avatar")
SPEND_REF = "chat_message"


# ── rows ────────────────────────────────────────────────────────────────────

def message_row(message_id: int) -> dict:
    row = db.get("chat_messages", int(message_id))
    if row is None:
        raise NotFound("chat_message", id=message_id)
    return row


def next_position(chat_id: int) -> int:
    return int(db.fetch_value("SELECT COALESCE(MAX(position), 0) FROM chat_messages WHERE chat_id = ?",
                              (chat_id,), 0)) + 1


def add_message(chat_id: int, *, type: str, kind: str = "text", mode: str | None = None, text: str = "",
                attachments: list | None = None, settings: dict | None = None, reply_to: int | None = None,
                request_id: int | None = None, refs: dict | None = None, data: dict | None = None,
                status: str = "done", cost_usd: float = 0.0, error_code: str | None = None,
                error: str | None = None) -> int:
    now = db.now()
    message_id = db.insert("chat_messages", {
        "chat_id": chat_id, "position": next_position(chat_id), "type": type, "kind": kind, "mode": mode,
        "text": text, "attachments_json": attachments or [], "settings_json": settings or {},
        "reply_to": reply_to, "request_id": request_id, "refs_json": refs or {}, "data_json": data or {},
        "status": status, "cost_usd": round(cost_usd or 0, 6), "error_code": error_code,
        "error": (error or "")[:4000] or None, "created_at": now, "updated_at": now,
    })
    store.touch(chat_id, message=True)
    return message_id


def update_message(message_id: int, values: dict) -> None:
    values = dict(values)
    if "error" in values and values["error"]:
        values["error"] = str(values["error"])[:4000]
    values["updated_at"] = db.now()
    db.update("chat_messages", message_id, values)


def link_refs(message_id: int, chat_id: int, refs: list[tuple[str, int]]) -> None:
    for ref_type, ref_id in refs:
        if ref_type not in REF_TYPES or not ref_id:
            continue
        db.execute("INSERT OR IGNORE INTO chat_result_refs (message_id, chat_id, ref_type, ref_id) "
                   "VALUES (?, ?, ?, ?)", (message_id, chat_id, ref_type, int(ref_id)))


# ── keeping results up to date ──────────────────────────────────────────────

def _job(job_id: Any) -> dict | None:
    return db.get("jobs", int(job_id)) if job_id else None


def _version_of(frame: dict | None, file_id: Any) -> dict:
    for v in reversed((frame or {}).get("versions_json") or []):
        if file_id and v.get("file_id") == file_id:
            return v
    return {}


def _image_item(item: dict) -> dict:
    """One picture of a result: looks at its job and frame while it is not final."""
    if item.get("status") in FINAL:
        return item
    out = dict(item)
    frame = db.get("frames", int(item["frame_id"])) if item.get("frame_id") else None
    if frame is None:
        out.update(status="error", error_code="frame_gone", error=None)
        return out
    if not out.get("job_id"):
        # A pilot's follower that waits for "Accept": it is drawn once the frame gets a full job.
        job = _job(frame.get("job_id"))
        if job is not None and (job.get("payload_json") or {}).get("mode") == "full" and job["id"] > int(
                out.get("after_job") or 0):
            out["job_id"] = job["id"]
        else:
            out["status"] = "waiting"
            return out
    job = _job(out["job_id"])
    if job is None:
        out.update(status="error", error_code="job_gone", error=None)
        return out
    if job["status"] in ACTIVE:
        busy = frame.get("job_id") == job["id"] and frame["status"] == "drawing"
        out["status"] = "running" if busy or job["status"] == "running" else "queued"
        out["progress"] = job.get("progress")
        return out
    if job["status"] == "done":
        result = job.get("result_json") or {}
        file_id = result.get("file_id")
        if not file_id or result.get("frame_gone"):
            out.update(status="error", error_code="frame_gone", error=None)
            return out
        v = _version_of(frame, file_id)
        out.update(status="done", file_id=file_id, cost_usd=round(result.get("cost_usd") or 0, 6),
                   prompt_text=v.get("prompt_text"), model_id=v.get("model_id"), image_size=v.get("image_size"),
                   error_code=None, error=None)
        out.pop("progress", None)
        return out
    if job["status"] == "cancelled":
        out.update(status="cancelled", error_code="cancelled", error=None)
    else:
        text = frame.get("error_text") if frame.get("job_id") == job["id"] else None
        out.update(status="error", error_code=job.get("error_code") or job["status"],
                   error=text or job.get("error"), prompt_text=frame.get("prompt_text"))
    out.pop("progress", None)
    return out


def _clip_version(run_id: int, clip_id: int) -> dict | None:
    for v in db.fetch_all("SELECT * FROM video_versions WHERE run_id = ? ORDER BY number", (run_id,)):
        ids = v.get("clip_ids_json") or []
        if ids and int(ids[-1]) == int(clip_id):
            return v
    return None


def _video_item(item: dict) -> dict:
    """One video of a result: looks at its clip while it is not final."""
    if item.get("status") in FINAL:
        return item
    from vf.modules.video import generate as video_generate

    out = dict(item)
    clip = db.get("video_clips", int(item["clip_id"])) if item.get("clip_id") else None
    if clip is None:
        out.update(status="error", error_code="video_gone", error=None)
        return out
    video_generate.settle(clip["run_id"])
    clip = db.get("video_clips", clip["id"])
    out.update(prompt=clip.get("prompt") or clip.get("next_text"), model_id=clip.get("model_id"),
               seconds=clip.get("seconds"), resolution=clip.get("resolution"), kind=clip.get("kind"))
    if clip["status"] in ACTIVE:
        job = _job(clip.get("job_id"))
        out["status"] = clip["status"]
        out["progress"] = job.get("progress") if job else None
        return out
    out.pop("progress", None)
    if clip["status"] == "done":
        v = _clip_version(clip["run_id"], clip["id"])
        out.update(status="done", version=v["number"] if v else None,
                   file_id=v["file_id"] if v else clip.get("file_id"), cost_usd=round(clip.get("cost_usd") or 0, 6),
                   duration=v.get("duration") if v else None, error_code=None, error=None)
        return out
    if clip["status"] == "cancelled":
        out.update(status="cancelled", error_code="cancelled", error=None, cost_usd=round(clip.get("cost_usd") or 0, 6))
    else:
        out.update(status="error", error_code=clip.get("error_code") or "error", error=clip.get("error"),
                   cost_usd=round(clip.get("cost_usd") or 0, 6))
    return out


def aggregate(items: list[dict]) -> str:
    states = [i.get("status") for i in items if i.get("status") != "waiting"]
    if any(s in ACTIVE for s in states):
        return "running"
    if not states:
        return "done"
    if all(s == "error" for s in states):
        return "error"
    if all(s == "cancelled" for s in states):
        return "cancelled"
    return "done"


def hydrate(row: dict) -> dict:
    """Bring a result message up to date with its frames or clips; saves what changed."""
    if row["type"] != "result" or row["status"] in FINAL and not _has_open(row):
        return row
    data = dict(row.get("data_json") or {})
    items = list(data.get("items") or [])
    if row["kind"] == "image":
        fresh = [_image_item(i) for i in items]
    elif row["kind"] == "video":
        fresh = [_video_item(i) for i in items]
    else:
        return row
    status = aggregate(fresh) if fresh else row["status"]
    cost = round(sum(float(i.get("cost_usd") or 0) for i in fresh), 6)
    first_error = next((i for i in fresh if i.get("status") == "error"), None)
    error_code = row.get("error_code")
    error = row.get("error")
    if status == "error" and first_error:
        error_code, error = first_error.get("error_code"), first_error.get("error")
    elif status != "error" and row.get("error_code") and items:
        error_code, error = None, None
    if fresh == items and status == row["status"] and cost == round(row.get("cost_usd") or 0, 6) \
            and error_code == row.get("error_code"):
        return row
    data["items"] = fresh
    values = {"data_json": data, "status": status, "cost_usd": cost, "error_code": error_code, "error": error}
    update_message(row["id"], values)
    return {**row, **values}


def _has_open(row: dict) -> bool:
    return any(i.get("status") not in FINAL for i in (row.get("data_json") or {}).get("items") or [])


# ── the view sent to the browser ────────────────────────────────────────────

def _file(file_id: Any) -> dict | None:
    if not file_id:
        return None
    try:
        return files.public(files.get(int(file_id)))
    except NotFound:
        return None


def _spend_link(ref_type: str, ref_id: Any) -> str | None:
    return f"/settings/spend?ref_type={ref_type}&ref_id={ref_id}&period=all" if ref_id else None


def _item_view(kind: str, item: dict) -> dict:
    out = dict(item)
    out["file"] = _file(item.get("file_id"))
    if kind == "image":
        out["spend_link"] = _spend_link("frame", item.get("frame_id"))
    elif kind == "video":
        out["spend_link"] = _spend_link("video_clip", item.get("clip_id"))
    return out


def _attachments_view(items: list[dict]) -> list[dict]:
    return [{**a, "file": _file(a.get("file_id"))} for a in items or []]


def reply_brief(message_id: int | None, index: int | None = None) -> dict | None:
    """What a reply shows above the text: the message and the picture or video replied to."""
    if not message_id:
        return None
    row = db.get("chat_messages", int(message_id))
    if row is None:
        return None
    items = (row.get("data_json") or {}).get("items") or []
    item = items[index] if index is not None and 0 <= index < len(items) else (items[0] if items else None)
    file = _file(item.get("file_id")) if item else None
    return {"id": row["id"], "type": row["type"], "kind": row["kind"], "mode": row["mode"],
            "text": (row.get("text") or "")[:160], "index": index,
            "thumb_url": file["thumb_url"] if file else None}


def public(row: dict, *, fresh: bool = True) -> dict:
    if fresh:
        row = hydrate(row)
    data = dict(row.get("data_json") or {})
    if row["kind"] in ("image", "video") and row["type"] == "result":
        data["items"] = [_item_view(row["kind"], i) for i in data.get("items") or []]
    snap = row.get("settings_json") or {}
    reply_index = (snap.get("reply") or {}).get("index") if row["type"] == "request" else None
    return {
        "id": row["id"], "chat_id": row["chat_id"], "position": row["position"], "type": row["type"],
        "kind": row["kind"], "mode": row.get("mode"), "text": row.get("text") or "",
        "attachments": _attachments_view(row.get("attachments_json") or []), "settings": snap,
        "reply_to": row.get("reply_to"), "reply": reply_brief(row.get("reply_to"), reply_index),
        "request_id": row.get("request_id"), "refs": row.get("refs_json") or {}, "data": data,
        "status": row["status"], "cost_usd": round(row.get("cost_usd") or 0, 6),
        "error_code": row.get("error_code"), "error": row.get("error"),
        "spend_link": _spend_link(SPEND_REF, row["id"]) if row["type"] == "request" else None,
        "link": f"/chat/{row['chat_id']}?message={row['id']}",
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def get_message(message_id: int) -> dict:
    return public(message_row(message_id))


def list_messages(chat_id: int, *, before: int | None = None, limit: int = 60) -> dict:
    """Newest ``limit`` messages before position ``before`` (all when None), oldest first."""
    store.chat_row(chat_id)
    limit = max(1, min(int(limit or 60), 200))
    params: list[Any] = [chat_id]
    sql = "SELECT * FROM chat_messages WHERE chat_id = ?"
    if before:
        sql += " AND position < ?"
        params.append(int(before))
    rows = db.fetch_all(sql + " ORDER BY position DESC LIMIT ?", [*params, limit + 1])
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    return {"items": [public(r) for r in rows], "more": more}


def result_item(message: dict, index: Any) -> dict:
    items = (message.get("data_json") or {}).get("items") or []
    try:
        i = int(index or 0)
    except (TypeError, ValueError):
        i = -1
    if not 0 <= i < len(items):
        raise AppError("chat_item_unknown", 404, "There is no such picture or video in this message", index=index)
    return items[i]


def settle_all() -> int:
    """Startup: requests left "enhancing" by a stop of the app are closed with an error."""
    rows = db.fetch_all("SELECT id FROM chat_messages WHERE status = 'enhancing'")
    for row in rows:
        update_message(row["id"], {"status": "error", "error_code": "interrupted",
                                   "error": "The app stopped while the prompt was being improved"})
    return len(rows)


# ── finding a result by link ────────────────────────────────────────────────

def find(*, frame: Any = None, work: Any = None, video: Any = None) -> dict:
    """``/chat?frame=…|work=…|video=…``: the chat and message that hold it (None when no chat does)."""
    if frame:
        ref_type, ref_id, table = "frame", int(frame), "frames"
    elif work:
        ref_type, ref_id, table = "work", int(work), "image_works"
    elif video:
        ref_type, ref_id, table = "video_run", int(video), "video_runs"
    else:
        raise AppError("bad_request", 400, "Say what to find: frame, work or video")
    row = db.get(table, ref_id)
    if row is None:
        raise NotFound(table, id=ref_id)
    hit = db.fetch_one(
        "SELECT r.chat_id, r.message_id FROM chat_result_refs r JOIN chats c ON c.id = r.chat_id "
        "WHERE r.ref_type = ? AND r.ref_id = ? ORDER BY r.message_id DESC LIMIT 1", (ref_type, ref_id))
    out: dict[str, Any] = {"ref_type": ref_type, "ref_id": ref_id, "chat_id": None, "message_id": None,
                           "work_id": None, "frame_id": None, "run_id": None}
    if ref_type == "frame":
        out.update(frame_id=ref_id, work_id=row["work_id"])
    elif ref_type == "work":
        out["work_id"] = ref_id
    else:
        out["run_id"] = ref_id
    if hit:
        out.update(chat_id=hit["chat_id"], message_id=hit["message_id"])
    return out
