"""Updates screen (module 14, app side).

The ``updater`` container does the work: it checks releases, backs up the
database, pulls images and restarts the app. This package only talks to it
for the browser (``/api/updates/...``) and cleans its answers so that only
known fields reach the page. The updater token never leaves the server.
"""

from vf.modules.updates.routes import router

__all__ = ["router"]
