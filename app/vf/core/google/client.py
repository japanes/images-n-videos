"""One google-genai client per Vertex region, built from the stored key."""

from __future__ import annotations

import threading

from google import genai
from google.genai import types

from vf.core import settings
from vf.core.google import credentials

_lock = threading.Lock()
_clients: dict[tuple[str, str, int], genai.Client] = {}


def get_client(region: str | None = None) -> genai.Client:
    region = region or "global"
    timeout_ms = int(settings.get("google.timeout_seconds")) * 1000
    key = (region, credentials.fingerprint(), timeout_ms)
    with _lock:
        client = _clients.get(key)
        if client is None:
            for stale in [k for k in _clients if k[0] == region]:
                _clients.pop(stale, None)
            client = genai.Client(
                vertexai=True,
                project=credentials.project_id(),
                location=region,
                credentials=credentials.load_credentials(),
                http_options=types.HttpOptions(timeout=timeout_ms),
            )
            _clients[key] = client
        return client


def reset_clients() -> None:
    with _lock:
        _clients.clear()


credentials.on_change(reset_clients)
