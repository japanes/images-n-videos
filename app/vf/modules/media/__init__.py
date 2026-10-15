"""Module 10 — media library: uploads, video intake, the library screen API,
"where is it used", daily cleanup of service leftovers.

For other modules:
- upload from the browser: ``POST /api/media/upload`` (multipart ``file``,
  optional ``title``, optional ``kinds=image,video,audio,font``);
- after registering a video or audio file: ``enqueue_video_ingest(file_id)``
  (poster, hover preview, duration, size through ``render``);
- report usages with ``@files.usage_provider`` (``vf.core.files``).
"""

from vf.modules.media import cleanup, ingest, library, upload
from vf.modules.media.ingest import enqueue_video_ingest
from vf.modules.media.routes import router

__all__ = ["cleanup", "enqueue_video_ingest", "ingest", "library", "router", "upload"]
