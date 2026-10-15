"""Small HTTP client on urllib (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

USER_AGENT = "vertexai-factory-updater"


class HttpResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8") or "null")

    def header(self, name: str, default=None):
        return self.headers.get(name.lower(), default)


class HttpError(Exception):
    """Network-level failure (no HTTP response)."""


def request(method: str, url: str, headers=None, body=None, timeout: float = 15,
            max_bytes: int = 4 * 1024 * 1024) -> HttpResponse:
    data = None
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise HttpError(f"response from {url} is too large")
            return HttpResponse(resp.status, dict(resp.headers.items()), payload)
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read(max_bytes) or b""
        except Exception:
            payload = b""
        finally:
            exc.close()
        return HttpResponse(exc.code, dict(exc.headers.items()) if exc.headers else {}, payload)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpError(f"{method} {url}: {reason}") from None
