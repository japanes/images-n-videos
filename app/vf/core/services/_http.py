"""Shared HTTP helper for the sibling services."""

from __future__ import annotations

from typing import Any

import httpx

from vf.core.errors import AppError


async def call(service: str, method: str, url: str, *, json: Any = None, headers: dict | None = None,
               timeout: float = 30.0, ok_statuses: tuple[int, ...] = ()) -> Any:
    """JSON request to a sibling service. Maps failures to ``<service>_unavailable`` /
    ``<service>_failed`` AppErrors carrying the service's own error code and text."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, json=json, headers=headers)
    except httpx.HTTPError as exc:
        raise AppError(f"{service}_unavailable", 503, f"{service} service is not reachable: {exc}") from exc
    if resp.status_code >= 400 and resp.status_code not in ok_statuses:
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = {"message": resp.text[:2000]}
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, str) and err:
            err = {"message": err}  # render's /health answers {"ok": false, "error": "..."}
        if not isinstance(err, dict):
            err = {"message": str(body)[:2000]}
        raise AppError(f"{service}_failed", 502, err.get("message") or f"{service} error",
                       service_code=err.get("code"), service_status=resp.status_code,
                       stderr_tail=err.get("stderr_tail"))
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text
