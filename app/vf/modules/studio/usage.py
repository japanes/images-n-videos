"""Links from the rest of the app into the studio.

- media library: a picture shown in a frame, or picked as a reference or an
  attachment, cannot be deleted while the work uses it (older versions can);
- spend screen: journal refs "work" and "frame" get a title and a link;
- every minute: frames left behind by a restart or a hung request are put in order.
"""

from __future__ import annotations

from vf.core import db, files, scheduler
from vf.modules.spend import register_ref
from vf.modules.studio import generate
from vf.modules.studio import works as W

USAGE_TYPE = "studio"


def _title(work_id: int, title: str | None) -> str:
    return title or f"#{work_id}"


@files.usage_provider
def _studio_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT w.id, w.title FROM image_works w WHERE "
        " EXISTS (SELECT 1 FROM frames f WHERE f.work_id = w.id AND (f.file_id = :id OR f.clean_file_id = :id))"
        " OR EXISTS (SELECT 1 FROM json_each(w.settings_json, '$.references') j WHERE j.value = :id)"
        " OR EXISTS (SELECT 1 FROM frames f, json_each(f.overrides_json, '$.references') j"
        "            WHERE f.work_id = w.id AND j.value = :id)"
        " OR EXISTS (SELECT 1 FROM frames f, json_each(f.overrides_json, '$.attachments') j"
        "            WHERE f.work_id = w.id AND j.value = :id)"
        " ORDER BY w.id",
        {"id": file_id})
    return [{"type": USAGE_TYPE, "id": r["id"], "title": _title(r["id"], r["title"])} for r in rows]


def _work_ref(work_id: int) -> dict | None:
    row = db.get("image_works", work_id)
    if row is None:
        return None
    cover = db.fetch_value("SELECT file_id FROM frames WHERE work_id = ? AND file_id IS NOT NULL "
                           "ORDER BY position, id LIMIT 1", (work_id,))
    return {"title": _title(work_id, row["title"]), "link": f"/chat?work={work_id}",
            "thumb_url": files.url(cover, w=160) if cover else None}


def _frame_ref(frame_id: int) -> dict | None:
    row = db.get("frames", frame_id)
    if row is None:
        return None
    work = db.get("image_works", row["work_id"])
    title = f"{_title(row['work_id'], work['title'] if work else None)} · {row['position'] + 1}"
    out = {"title": title, "link": f"/chat?frame={frame_id}"}
    if row.get("file_id") and db.get("files", row["file_id"]) is not None:
        out["url"] = files.url(row["file_id"])
        out["thumb_url"] = files.url(row["file_id"], w=160)
    return out


register_ref(W.REF_WORK, _work_ref)
register_ref(W.REF_FRAME, _frame_ref)


@scheduler.every_minute
async def _sweep_frames() -> None:
    # On the event loop (not in a thread): stopping a hung job touches asyncio tasks.
    generate.sweep()
