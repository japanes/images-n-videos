"""Module 13 (app side): the jobs page, service health, minute and daily housekeeping."""

from vf.modules.jobs_ui import maintenance as _maintenance  # noqa: F401  (settings + scheduler hooks)
from vf.modules.jobs_ui.routes import router

__all__ = ["router"]
