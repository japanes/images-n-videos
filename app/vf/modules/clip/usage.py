"""Which clip projects use a file: the source video, the last preview, and the
pictures, fonts and sound tracks the edits point at (also brand kit fonts in
the project's brand snapshot). The media library calls this for every file it
lists, so it is one SQL query over the stored JSON.

The usage type is "project": the media screen already labels it
(`media.usageTypes.project`, "Video editor project").

Exported files are NOT reported: an export is a finished, independent video
that the person may delete like any other.
"""

from __future__ import annotations

from vf.core import db, files

_SQL = """
SELECT DISTINCT p.id, p.title FROM clip_projects p
WHERE p.file_id = :fid OR p.preview_file_id = :fid
   OR EXISTS (SELECT 1 FROM json_each(p.state_json, '$.layers') l
              WHERE json_extract(l.value, '$.file_id') = :fid
                 OR json_extract(l.value, '$.font_file_id') = :fid)
   OR EXISTS (SELECT 1 FROM json_each(p.state_json, '$.audio.tracks') t
              WHERE json_extract(t.value, '$.file_id') = :fid)
   OR (p.brand_json IS NOT NULL AND json_valid(p.brand_json) AND EXISTS (
          SELECT 1 FROM json_each(p.brand_json, '$.fonts') f WHERE json_extract(f.value, '$.file_id') = :fid))
ORDER BY p.id
"""


@files.usage_provider
def clip_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(_SQL, {"fid": int(file_id)})
    return [{"type": "project", "id": r["id"], "title": r["title"] or f"#{r['id']}", "url": f"/clip/{r['id']}"}
            for r in rows]
