"""Refuses requests that other web sites send to the app.

The app has no login: it trusts that only the person at this computer reaches
127.0.0.1. But any page open in their browser can send requests there too:
- a plain form post or ``fetch`` from another site could start a paid generation,
  delete the key or stop the app (cross-site request);
- a site whose DNS name points at 127.0.0.1 could even read the answers
  (DNS rebinding).

Two checks stop both, for every request before it reaches a route:
- the ``Host`` header must name this computer (or a compose service name);
- a request that changes something (not GET/HEAD/OPTIONS) must come from the
  app's own page: ``Sec-Fetch-Site`` is ``same-origin`` or ``none``, or, from a
  browser that does not send it, ``Origin`` names this computer.

Requests without these headers (curl, health checks) pass.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

log = logging.getLogger("vf.guard")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SAME_SITE_FETCH = frozenset({"same-origin", "none"})


def host_name(value: str) -> str:
    """``Host`` header or URL netloc → lower-case name without port or brackets."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value[1:]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def refusal(method: str, headers: dict[str, str], allowed: frozenset[str]) -> str | None:
    """Why the request is refused, or None when it may pass."""
    host = headers.get("host")
    if host is not None and host_name(host) not in allowed:
        return "host"
    if method in SAFE_METHODS:
        return None
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return None if fetch_site.strip().lower() in SAME_SITE_FETCH else "cross_site"
    origin = headers.get("origin")
    if origin is not None:
        if origin.strip().lower() == "null":
            return "cross_site"
        if host_name(urlsplit(origin.strip()).netloc) not in allowed:
            return "cross_site"
    return None


class SameSiteGuard:
    """Pure ASGI middleware, so event streams pass through untouched."""

    def __init__(self, app, *, allowed_hosts) -> None:
        self.app = app
        self.allowed = frozenset(host_name(h) for h in allowed_hosts if h.strip())

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        reason = refusal(scope.get("method", "GET").upper(), headers, self.allowed)
        if reason is None:
            await self.app(scope, receive, send)
            return
        log.warning("refused a %s request to %s from another site (%s)", scope.get("method"),
                    scope.get("path"), reason)
        body = json.dumps({"error": {"code": "forbidden", "message": "requests from other sites are not accepted",
                                     "details": {"reason": reason}}}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
