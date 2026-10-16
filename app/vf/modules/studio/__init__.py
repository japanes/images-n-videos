"""Image studio (module 04): works of 1–10 frames with shared settings, drawn by
Gemini image models; corrections of one object; free rollback to earlier versions.

HTTP: /api/studio/… (contract in docs/dev/studio-api.md). Python API for the chat (15)::

    from vf.modules import studio

    work = studio.create_work({"title": "Sale", "aspect": "4:5", "frame_count": 4,
                               "settings": {"series": True, "ideas_brief": "…"}})
    studio.update_frame(frame_id, {"brief": "…", "overrides": {"references": [file_id]}})
    studio.start_all(work_id)            # {queued, skipped, work}; each frame is one paid request
    studio.accept_pilot(work_id)         # series: the others follow the first frame's look
    studio.start_frame(frame_id)         # draw one frame again
    studio.start_edit(frame_id, "make the cup red", {"id": "cup"})  # or {"label", "box"} by hand
    await studio.find_objects(frame_id, focus="")                    # {objects, cached, frame}
    studio.restore_version(frame_id, index)                          # free, instant
    studio.pick_picture(frame_id, file_id, source="avatar", source_ref={"avatar_id": 3})
    studio.estimate({"action": "generate_all", "work_id": work_id})  # price before the button
    studio.get_work(work_id) / studio.frame_public(row)              # the views the browser gets

Journal refs: ("work", id) and ("frame", id); purposes "frame", "frame_edit", "regions". Job kind: "studio.frame" (group "image").
Events: "studio.updated" with {what: "work"|"frame", work_id, frame_id?, status?, deleted?}.
"""

from vf.modules.studio import usage as _usage  # noqa: F401  (media usages, spend refs, sweeper)
from vf.modules.studio.estimate import estimate
from vf.modules.studio.export import build_zip
from vf.modules.studio.generate import (
    JOB_KIND,
    accept_pilot,
    cancel_frame,
    run_frame,
    start_all,
    start_edit,
    start_frame,
    sweep,
)
from vf.modules.studio.objects import find_objects
from vf.modules.studio.routes import router
from vf.modules.studio.sources import pick_picture, restore_version, upload_picture
from vf.modules.studio.works import (
    REF_FRAME,
    REF_WORK,
    add_frame,
    create_work,
    delete_frame,
    delete_work,
    frame_public,
    get_work,
    list_works,
    update_frame,
    update_work,
)

__all__ = [
    "JOB_KIND", "REF_FRAME", "REF_WORK", "accept_pilot", "add_frame", "build_zip", "cancel_frame", "create_work",
    "delete_frame", "delete_work", "estimate", "find_objects", "frame_public", "get_work", "list_works",
    "pick_picture", "restore_version", "router", "run_frame", "start_all", "start_edit", "start_frame",
    "sweep", "update_frame", "update_work", "upload_picture",
]
