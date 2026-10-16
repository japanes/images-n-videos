"""Clip editor (module 12): cut a video, crop it to a format, add subtitles from
speech (local ``stt``, free), text and picture layers, music and sound; export
is a new file in the media library, the source is never changed.

Python API for the chat (15) and other modules::

    from vf.modules import clip

    await clip.open_project(file_id)            # newest project of this video (or a new one)
    await clip.open_project(file_id, new=True)  # always a new project
    clip.list_projects(file_id)                 # short lines, newest first

In the browser the editor opens at ``/clip/<project id>``; ``/clip/new?file=<file id>``
opens (or creates) the project of a video and switches to its address.

No Google model is called here, so there is nothing to price or to journal.
"""

from vf.modules.clip import export, transcribe, usage  # noqa: F401 - job handlers, settings, usage provider
from vf.modules.clip.projects import get_project, list_projects, open_project
from vf.modules.clip.routes import router

__all__ = ["get_project", "list_projects", "open_project", "router"]
