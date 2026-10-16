"""Links from the rest of the app into the chat.

- media library: a picture attached to a message or lying in a composer draft
  cannot be deleted while a chat (not archived) holds it. Results are not listed
  here: they live in studio works and video runs, which report their own usages;
- spend screen: journal refs "chat" and "chat_message" get a title and a link.
"""

from __future__ import annotations

from vf.core import db, files
from vf.modules.spend import register_ref

USAGE_TYPE = "chat"
REF_CHAT = "chat"
REF_MESSAGE = "chat_message"


def _title(chat: dict) -> str:
    return chat.get("title") or f"#{chat['id']}"


@files.usage_provider
def _chat_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT c.id, c.title FROM chats c WHERE c.archived_at IS NULL AND ("
        " EXISTS (SELECT 1 FROM chat_messages m, json_each(m.attachments_json) j"
        "         WHERE m.chat_id = c.id AND json_extract(j.value, '$.file_id') = :id)"
        " OR EXISTS (SELECT 1 FROM json_each(c.draft_json, '$.attachments') j"
        "            WHERE json_extract(j.value, '$.file_id') = :id))"
        " ORDER BY c.id",
        {"id": file_id})
    return [{"type": USAGE_TYPE, "id": r["id"], "title": _title(r), "link": f"/chat/{r['id']}"} for r in rows]


def _chat_ref(chat_id: int) -> dict | None:
    row = db.get("chats", chat_id)
    if row is None:
        return None
    return {"title": _title(row), "link": f"/chat/{chat_id}"}


def _message_ref(message_id: int) -> dict | None:
    row = db.get("chat_messages", message_id)
    if row is None:
        return None
    chat = db.get("chats", row["chat_id"]) or {"id": row["chat_id"], "title": ""}
    text = " ".join((row.get("text") or "").split())
    if len(text) > 60:
        text = text[:59].rstrip() + "…"
    return {"title": text or _title(chat), "link": f"/chat/{row['chat_id']}?message={message_id}"}


register_ref(REF_CHAT, _chat_ref)
register_ref(REF_MESSAGE, _message_ref)
