"""Calls from the updater to the app and to an updater instance over the compose network.

App contract (the app must implement it):
  GET  /health                          -> {"ok": true, "version": "X.Y.Z", ...}
  POST /api/internal/updates/prepare    header X-VF-Token, body {"target_version", "ttl_seconds"}
                                        -> {"ok": true} or {"ok": false, "busy": [{"kind", "title"}]}
  POST /api/internal/updates/resume     header X-VF-Token -> {"ok": true}
The token is the content of /data/update/token.
"""

from __future__ import annotations

from .http_util import HttpError, request

TOKEN_HEADER = "X-VF-Token"


class AppUnreachable(Exception):
    pass


class AppClient:
    def __init__(self, cfg, store, http=request):
        self.cfg = cfg
        self.store = store
        self.http = http

    def _headers(self):
        return {TOKEN_HEADER: self.store.read_token()}

    def prepare(self, target_version: str, ttl_seconds: int = 1800) -> dict:
        """Ask the app to pause new jobs. Returns {"ok": bool, "busy": [...]}."""
        try:
            resp = self.http("POST", f"{self.cfg.app_url}/api/internal/updates/prepare",
                             headers=self._headers(),
                             body={"target_version": target_version, "ttl_seconds": ttl_seconds},
                             timeout=15)
        except HttpError as exc:
            raise AppUnreachable(str(exc)) from None
        if resp.status in (401, 403):
            raise AppUnreachable("the app did not accept the update token")
        if resp.status >= 500 or resp.status in (404, 405):
            raise AppUnreachable(f"prepare answered HTTP {resp.status}")
        try:
            data = resp.json()
        except ValueError:
            raise AppUnreachable("prepare returned invalid JSON") from None
        if not isinstance(data, dict):
            raise AppUnreachable("prepare returned an unexpected answer")
        busy = data.get("busy") if isinstance(data.get("busy"), list) else []
        busy = [
            {"kind": str(b.get("kind", "")), "title": str(b.get("title", ""))}
            for b in busy if isinstance(b, dict)
        ][:50]
        return {"ok": bool(data.get("ok")) and resp.status == 200, "busy": busy}

    def resume(self) -> bool:
        try:
            resp = self.http("POST", f"{self.cfg.app_url}/api/internal/updates/resume",
                             headers=self._headers(), body={}, timeout=15)
        except HttpError:
            return False
        return resp.status == 200


def health_version(url: str, http=request, timeout: float = 5):
    """Version reported by GET <url>/health, or None when not healthy."""
    try:
        resp = http("GET", f"{url}/health", timeout=timeout)
    except HttpError:
        return None
    if resp.status != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("ok") is False:
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None
