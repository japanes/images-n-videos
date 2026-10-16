"""The avatar's messages in its chat: the card, the identity, a batch of face
candidates, a batch of shots. A batch message follows its pictures: running while
one is drawn, then done / error / cancelled, with the money from the journal."""

from __future__ import annotations

from typing import Any

from vf.core import db
from vf.core.errors import AppError
from vf.core.google import journal
from vf.modules.avatars.common import BUSY, REF_AVATAR, REF_MESSAGE, log


def post(avatar: dict, kind: str, *, text: str = "", data: dict | None = None, status: str = "done") -> int | None:
    """A message in the avatar chat; None when the avatar has no chat (it was removed)."""
    from vf.modules import chat

    if not avatar.get("chat_id"):
        return None
    try:
        message = chat.post_message(avatar["chat_id"], kind=kind, text=text,
                                    data={"avatar_id": avatar["id"], **(data or {})},
                                    links=[(REF_AVATAR, avatar["id"])], status=status)
    except AppError as exc:
        log.info("avatar %s: no message posted (%s)", avatar["id"], exc.code)
        return None
    return message["id"]


def update(message_id: int | None, **values: Any) -> None:
    from vf.modules import chat

    if not message_id:
        return
    try:
        chat.update_posted(message_id, **values)
    except AppError:
        pass   # the message (or the chat) was deleted


def status_of(rows: list[dict], previous: str | None = None) -> str | None:
    if not rows:
        return previous
    if any(r["status"] in BUSY for r in rows):
        return "running"
    if any(r.get("file_id") and r["status"] == "done" for r in rows):
        return "done"
    if any(r["status"] == "error" for r in rows):
        return "error"
    return "cancelled"


def refresh(message_id: int | None) -> None:
    """Status and money of a batch message, from the pictures it still shows."""
    if not message_id:
        return
    msg = db.get("chat_messages", message_id)
    if msg is None:
        return
    rows = db.fetch_all("SELECT * FROM avatar_photos WHERE message_id = ? AND status != 'archived'", (message_id,))
    status = status_of(rows, msg["status"])
    failed = [r for r in rows if r["status"] == "error"]
    update(message_id, status=status, cost_usd=journal.cost_of(REF_MESSAGE, message_id),
           error_code=failed[0]["error_code"] if failed and status == "error" else None,
           error=None)
