"""HTTP routes of the chat (/api/chat/…). Contract: docs/dev/chat-api.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from vf.core.errors import AppError
from vf.modules.chat import messages, send, store, view

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _body(body: dict[str, Any] | None) -> dict[str, Any]:
    if body is not None and not isinstance(body, dict):
        raise AppError("bad_request", 400, "An object is expected")
    return dict(body or {})


def _int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, field=name) from None


# ── chats ───────────────────────────────────────────────────────────────────


@router.get("/chats")
async def list_chats(q: str | None = None, archived: bool = False, limit: int = 50, offset: int = 0) -> dict:
    return store.list_chats(q=q, archived=archived, limit=max(1, min(int(limit), 200)),
                            offset=max(0, int(offset)))


@router.post("/chats")
async def create_chat(body: dict[str, Any] | None = None) -> dict:
    return view.chat_public(store.create_chat(_body(body)))


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: int) -> dict:
    return view.get_chat(chat_id)


@router.patch("/chats/{chat_id}")
async def update_chat(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return view.chat_public(store.update_chat(chat_id, _body(body)))


@router.post("/chats/{chat_id}/archive")
async def archive_chat(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return view.chat_public(store.archive_chat(chat_id, bool(_body(body).get("archived", True))))


@router.get("/chats/{chat_id}/messages")
async def list_messages(chat_id: int, before: int | None = None, limit: int = 60) -> dict:
    return messages.list_messages(chat_id, before=before, limit=limit)


@router.get("/chats/{chat_id}/pictures")
async def pictures(chat_id: int, limit: int = 60) -> dict:
    return send.pictures(chat_id, max(1, min(int(limit), 200)))


# ── sending ─────────────────────────────────────────────────────────────────


@router.post("/chats/{chat_id}/estimate")
async def estimate(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return send.estimate(chat_id, _body(body))


@router.post("/chats/{chat_id}/send")
async def send_message(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return await send.send(chat_id, _body(body))


@router.post("/chats/{chat_id}/video-draft")
async def video_draft(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return send.video_draft(chat_id, _body(body))


@router.post("/chats/{chat_id}/from-viewer")
async def from_viewer(chat_id: int, body: dict[str, Any] | None = None) -> dict:
    return send.from_viewer(chat_id, _body(body))


# ── one message ─────────────────────────────────────────────────────────────


@router.get("/messages/{message_id}")
async def get_message(message_id: int) -> dict:
    return messages.get_message(message_id)


@router.get("/messages/{message_id}/repeat-estimate")
async def repeat_estimate(message_id: int, original: bool = False) -> dict:
    return send.repeat_estimate(message_id, original)


@router.post("/messages/{message_id}/repeat")
async def repeat(message_id: int, body: dict[str, Any] | None = None) -> dict:
    return await send.repeat(message_id, bool(_body(body).get("original")))


@router.get("/messages/{message_id}/accept-pilot/estimate")
async def accept_pilot_estimate(message_id: int) -> dict:
    return send.accept_pilot_estimate(message_id)


@router.post("/messages/{message_id}/accept-pilot")
async def accept_pilot(message_id: int) -> dict:
    return send.accept_pilot(message_id)


@router.post("/messages/{message_id}/cancel")
async def cancel(message_id: int) -> dict:
    return send.cancel(message_id)


@router.post("/messages/{message_id}/take-frame")
async def take_frame(message_id: int, body: dict[str, Any] | None = None) -> dict:
    return await send.take_frame(message_id, _body(body))


# ── links ───────────────────────────────────────────────────────────────────


@router.get("/find")
async def find(frame: str | None = None, work: str | None = None, video: str | None = None) -> dict:
    return messages.find(frame=_int(frame, "frame"), work=_int(work, "work"), video=_int(video, "video"))
