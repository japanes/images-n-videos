"""Chat (module 15): the place where pictures and videos are made — a feed of
requests and results, a composer, the settings of the chat on the side.

The chat is a wrapper: pictures stay frames of studio works (module 04), videos
stay video runs (module 11). A message only points at them, and a read of a
message brings it up to date with its frames and clips.

HTTP: /api/chat/… (contract in docs/dev/chat-api.md). Python API for other modules::

    from vf.modules import chat

    c = chat.create_chat({"kind": "avatar", "title": "…", "meta": {"avatar_id": 7}})
    chat.post_message(c["id"], kind="avatar.card", text="…", data={…},
                      links=[("avatar", 7)])                 # a message of a module's own kind
    chat.find(frame=12) / chat.find(work=3) / chat.find(video=5)   # which chat holds a result
    chat.get_chat(chat_id) / chat.get_message(message_id)        # the views the browser gets

Journal refs: ("chat", id) and ("chat_message", id) — the "Improve prompt" call
(purpose "prompt_enhance", prompt file chat.enhance). Generation calls are
journaled by the studio and the video modules with their own refs.
Events: "chat.updated" {chat_id, what: "chat"|"message", message_id?}.
"""

from __future__ import annotations

import re
from typing import Any

from vf.core.errors import AppError
from vf.modules.chat import messages, store
from vf.modules.chat import usage as _usage  # noqa: F401  (media usages, spend refs)
from vf.modules.chat.messages import find, get_message
from vf.modules.chat.routes import router
from vf.modules.chat.store import create_chat, update_chat
from vf.modules.chat.view import get_chat

MESSAGE_TYPES = ("request", "result", "service")
STATUSES = ("running", "done", "error", "cancelled")
_KIND = re.compile(r"^[a-z][a-z0-9_.-]{0,39}$")


def _status(status: str) -> str:
    if status not in STATUSES:
        raise AppError("bad_request", 400, "Unknown message status", status=status, allowed=list(STATUSES))
    return status


def post_message(chat_id: int, *, kind: str, text: str = "", data: dict | None = None, refs: dict | None = None,
                 links: list[tuple[str, int]] | None = None, type: str = "service", mode: str | None = None,
                 status: str = "done", cost_usd: float = 0.0, error_code: str | None = None,
                 error: str | None = None) -> dict:
    """Put a message of a module's own kind into a chat (it is drawn by
    ``web/components/chat/kinds/<Kind>.vue``). ``links`` make ``chat.find`` and
    the ``/chat?…`` links point at this message. Returns the message view."""
    store.chat_row(chat_id)
    if type not in MESSAGE_TYPES:
        raise AppError("bad_request", 400, "Unknown message type", type=type, allowed=list(MESSAGE_TYPES))
    if not isinstance(kind, str) or not _KIND.match(kind):
        raise AppError("bad_request", 400, "A message kind is a short lowercase name", kind=kind)
    if mode is not None and mode not in store.MODES:
        raise AppError("bad_request", 400, "Unknown mode", mode=mode, allowed=list(store.MODES))
    _status(status)
    message_id = messages.add_message(chat_id, type=type, kind=kind, mode=mode, text=text, refs=refs, data=data,
                                      status=status, cost_usd=cost_usd, error_code=error_code, error=error)
    if links:
        messages.link_refs(message_id, chat_id, list(links))
    store.publish(chat_id, what="message", message_id=message_id)
    return messages.get_message(message_id)


def update_posted(message_id: int, *, text: str | None = None, data: dict | None = None,
                  status: str | None = None, cost_usd: float | None = None, error_code: Any = ...,
                  error: Any = ...) -> dict:
    """Change a message posted with ``post_message`` (for example when the module's job finishes)."""
    row = messages.message_row(message_id)
    values: dict[str, Any] = {}
    if text is not None:
        values["text"] = text
    if data is not None:
        values["data_json"] = data
    if status is not None:
        values["status"] = _status(status)
    if cost_usd is not None:
        values["cost_usd"] = round(cost_usd, 6)
    if error_code is not ...:
        values["error_code"] = error_code
    if error is not ...:
        values["error"] = error
    if values:
        messages.update_message(message_id, values)
        store.publish(row["chat_id"], what="message", message_id=message_id)
    return messages.get_message(message_id)


async def on_startup() -> None:
    """Requests left "improving the prompt" by a stop of the app are closed with an error."""
    messages.settle_all()


__all__ = ["create_chat", "find", "get_chat", "get_message", "on_startup", "post_message", "router",
           "update_chat", "update_posted"]
