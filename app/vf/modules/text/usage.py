"""Links from the rest of the app into the «Text on image» tool.

- media library: a picture is «used» by a design while it is the design's background or a logo
  on one of its layers (deleting it anyway leaves the design without it: the columns are
  ``ON DELETE SET NULL`` and the renderer skips a logo that is gone);
- spend screen: the journal ref "text_design" gets a title and a link to the picture in its chat.
"""

from __future__ import annotations

from vf.core import db, files
from vf.modules.spend import register_ref
from vf.modules.text import common as C


def _title(row: dict) -> str:
    position = db.fetch_value("SELECT position FROM frames WHERE id = ?", (row["frame_id"],), None)
    frame = f" · {position + 1}" if position is not None else ""
    return f"Text on image{frame} · #{row['id']}"


def _link(row: dict) -> str:
    if row.get("chat_id") and row.get("message_id"):
        return f"/chat/{row['chat_id']}?message={row['message_id']}"
    if row.get("chat_id"):
        return f"/chat/{row['chat_id']}"
    return f"/chat?frame={row['frame_id']}"


@files.usage_provider
def _design_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT d.* FROM text_designs d WHERE d.background_file_id = :id"
        " OR EXISTS (SELECT 1 FROM json_each(d.layers_json) j"
        "            WHERE json_extract(j.value, '$.type') = 'logo' AND json_extract(j.value, '$.file_id') = :id)"
        " ORDER BY d.id",
        {"id": file_id})
    return [{"type": C.USAGE_TYPE, "id": r["id"], "title": _title(r), "link": _link(r)} for r in rows]


def _design_ref(design_id: int) -> dict | None:
    row = db.get("text_designs", design_id)
    if row is None:
        return None
    return {"title": _title(row), "link": _link(row)}


register_ref(C.REF_DESIGN, _design_ref)
