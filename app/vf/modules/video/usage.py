"""Links from the rest of the app into the video module.

- media library: a file a video uses (frames, references, the storyboard sheet,
  the finished versions and the clips) cannot be deleted while that video uses
  it; archived takes and undone versions do not count;
- spend screen: journal refs ``video_run`` and ``video_clip`` get a title, a link
  and a thumbnail.
"""

from __future__ import annotations

from vf.core import db, files
from vf.modules.spend import register_ref
from vf.modules.video import runs

USAGE_TYPE = "video"
CLIP_REF = "video_clip"


def _title(run: dict) -> str:
    return runs.job_title(run)


@files.usage_provider
def _video_usages(file_id: int) -> list[dict]:
    rows = db.fetch_all(
        "SELECT r.id, r.title, r.brief FROM video_runs r WHERE "
        " r.first_frame_id = :id OR r.last_frame_id = :id OR r.result_file_id = :id"
        " OR json_extract(r.storyboard_json, '$.file_id') = :id"
        " OR EXISTS (SELECT 1 FROM json_each(r.references_json) j WHERE j.value = :id)"
        " OR EXISTS (SELECT 1 FROM video_versions v WHERE v.run_id = r.id AND v.archived = 0"
        "            AND v.file_id = :id)"
        " OR EXISTS (SELECT 1 FROM video_clips c WHERE c.run_id = r.id AND c.archived = 0 AND c.file_id = :id)"
        " ORDER BY r.id",
        {"id": file_id})
    return [{"type": USAGE_TYPE, "id": r["id"], "title": _title(r)} for r in rows]


def _thumb(file_id: int | None) -> tuple[str | None, str | None]:
    row = runs.file_row(file_id)
    if row is None:
        return None, None
    pub = files.public(row)
    thumb = files.url(row["id"], w=160) if row["kind"] == "image" else pub["thumb_url"]
    return pub["url"], thumb


def _run_ref(run_id: int) -> dict | None:
    run = db.get("video_runs", run_id)
    if run is None:
        return None
    out = {"title": _title(run), "link": f"/chat?video={run_id}", "url": None, "thumb_url": None}
    out["url"], out["thumb_url"] = _thumb(run.get("result_file_id") or run.get("first_frame_id"))
    return out


def _clip_ref(clip_id: int) -> dict | None:
    clip = db.get("video_clips", clip_id)
    if clip is None:
        return None
    run = db.get("video_runs", clip["run_id"])
    title = f"{_title(run) if run else '#' + str(clip['run_id'])} · {clip['number']}"
    out = {"title": title, "link": f"/chat?video={clip['run_id']}" if run else None, "url": None, "thumb_url": None}
    out["url"], out["thumb_url"] = _thumb(clip.get("file_id"))
    return out


register_ref(runs.SOURCE, _run_ref)
register_ref(CLIP_REF, _clip_ref)

__all__ = ["USAGE_TYPE"]
