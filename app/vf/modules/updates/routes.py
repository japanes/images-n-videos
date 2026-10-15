"""HTTP API of the updates screen: ``/api/updates/...``.

Every call goes to the updater with the shared token; the browser never gets it.
Calls that change something refuse requests sent from other sites.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from vf.core.errors import AppError
from vf.modules.updates import service

router = APIRouter(prefix="/api/updates", tags=["updates"])


def same_origin(sec_fetch_site: str | None = Header(None)) -> None:
    """Browsers mark requests made by another site's page. Such a page could otherwise
    start an update or stop the app with a plain form post to 127.0.0.1."""
    if sec_fetch_site and sec_fetch_site.strip().lower() not in ("same-origin", "none"):
        raise AppError("forbidden", 403, "requests from other sites are not accepted")


class InstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=service.VERSION_LIMIT)
    force: StrictBool = False


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto: StrictBool | None = None
    time: str | None = Field(None, pattern=service.TIME_PATTERN)
    tz: str | None = Field(None, min_length=1, max_length=service.SHORT_LIMIT)
    channel: Literal["stable", "beta"] | None = None


@router.get("/status")
async def get_status() -> dict:
    """Versions, settings and the running operation. Answers 200 with ``reachable: false``
    when the updater is down, so the page can say so calmly."""
    return await service.overview()


@router.post("/check", dependencies=[Depends(same_origin)])
async def post_check() -> dict:
    return await service.check()


@router.post("/install", status_code=202, dependencies=[Depends(same_origin)])
async def post_install(body: InstallBody) -> dict:
    return await service.install(body.version, body.force)


@router.post("/settings", dependencies=[Depends(same_origin)])
async def post_settings(body: SettingsBody) -> dict:
    return await service.save_settings(body.model_dump(exclude_unset=True))


@router.post("/stop", status_code=202, dependencies=[Depends(same_origin)])
async def post_stop() -> dict:
    return await service.stop()


@router.get("/history")
async def get_history() -> dict:
    return await service.history()
