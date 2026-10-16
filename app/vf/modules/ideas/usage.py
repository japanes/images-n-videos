"""Links from the rest of the app into the idea sets.

- media library: a picture of a brief (product or visual reference) cannot be
  deleted while the set's chat is there and not archived — «Draw again» and the
  dice still send it;
- spend screen: the journal ref "ideas_set" gets a title (the concept, or the
  niche while there is none) and a link to the card in its chat.
"""

from __future__ import annotations

from vf.core import db, files
from vf.modules.ideas import common as C
from vf.modules.spend import register_ref


def _title(row: dict) -> str:
    concept = row.get("concept_json") or {}
    return concept.get("name") or (row.get("brief_json") or {}).get("niche") or f"#{row['id']}"


def _link(row: dict) -> str:
    if row.get("message_id"):
        return f"/chat/{row['chat_id']}?message={row['message_id']}"
    return f"/chat/{row['chat_id']}"


@files.usage_provider
def _set_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT s.* FROM ideas_sets s JOIN chats c ON c.id = s.chat_id"
        " WHERE c.archived_at IS NULL AND EXISTS (SELECT 1 FROM json_each(s.files_json) j WHERE j.value = :id)"
        " ORDER BY s.id",
        {"id": file_id})
    return [{"type": C.USAGE_TYPE, "id": r["id"], "title": _title(r), "link": _link(r)} for r in rows]


def _set_ref(set_id: int) -> dict | None:
    row = db.get("ideas_sets", set_id)
    if row is None:
        return None
    return {"title": _title(row), "link": _link(row)}


register_ref(C.REF_SET, _set_ref)
