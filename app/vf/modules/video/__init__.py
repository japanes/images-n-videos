"""Video (module 11): one take by Veo or Gemini Omni from a brief, frames and
references; «Write it for me»; a storyboard sheet; extension of a finished video
piece by piece by Omni with free rollback; «continue from the last frame».

HTTP: /api/video/… (contract in docs/dev/video-api.md). Python API for the chat (15)::

    from vf.modules import video

    run = video.create_run({"first_frame_id": file_id})       # «Animate» a picture
    video.update_run(run_id, {"brief": "…", "duration": 8})   # autosave of the form
    video.take_preview(video.get_run(run_id))                 # prompt, price or refusal
    video.start_take(run_id)                                  # one paid clip (job "video.take")
    video.extend.estimate(run_id, [{"text": "…", "seconds": 6}])
    video.extend.start_extend(run_id, steps, pause_each=True)  # job "video.extend" per piece
    video.extend.continue_plan(run_id) / video.stop_run(run_id) / video.undo_last(run_id)
    video.choose_version(run_id, number)                      # rollback, free
    await video.brief.write_brief(run_id, research=True)      # «Write it for me»
    await video.storyboard.make(run_id)                       # storyboard sheet
    await video.take_frame(run_id, at="last")                 # a picture for the studio
    video.public_run(run_id)                                  # the view the browser gets

Journal refs: ("video_run", id) and ("video_clip", id); purposes "video_take", "video_extend",
"video_continue", "video_brief", "video_research", "video_storyboard", "connection_check".
Job kinds: "video.take", "video.extend", "video.continue" (group "video", one at a time per video).
Events: "video.updated" (the full public view), "video.deleted" {id}.
"""

from vf.modules.video import brief, extend, storyboard
from vf.modules.video import checks as _checks  # noqa: F401  (live Omni check of the connection screen)
from vf.modules.video import usage as _usage  # noqa: F401  (media usages, spend refs)
from vf.modules.video.generate import run_continue, run_extend, run_take, sweep, take_frame
from vf.modules.video.routes import router
from vf.modules.video.runs import (
    JOB_CONTINUE,
    JOB_EXTEND,
    JOB_TAKE,
    SOURCE,
    choose_version,
    create_run,
    delete_run,
    get_run,
    list_runs,
    start_take,
    stop_run,
    take_preview,
    undo_last,
    update_run,
)
from vf.modules.video.view import public_run


async def on_startup() -> None:
    """Clips left behind by a restart are put in order before the job runner starts."""
    sweep()


__all__ = [
    "JOB_CONTINUE", "JOB_EXTEND", "JOB_TAKE", "SOURCE", "brief", "choose_version", "create_run", "delete_run",
    "extend", "get_run", "list_runs", "on_startup", "public_run", "router", "run_continue", "run_extend",
    "run_take", "start_take", "stop_run", "storyboard", "sweep", "take_frame", "take_preview", "undo_last",
    "update_run",
]
