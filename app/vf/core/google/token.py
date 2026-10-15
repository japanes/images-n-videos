"""Access tokens for the stored service-account key.

``check_token()`` is the first step of the connection check: it asks Google for
an OAuth access token (scope ``cloud-platform``). This is free, but it is the
call that catches a key deleted in the console, a broken file and a skewed
computer clock (``invalid_grant``), so it is journaled like any other call.

``bearer_token()`` is for adapters that talk to Vertex over plain HTTP
(Omni's Interactions API). It reuses the cached credentials and refreshes them
only when the token is missing or about to expire.
"""

from __future__ import annotations

import asyncio
import threading

from vf.core.config import get_config
from vf.core.google import credentials, journal, stub
from vf.core.google.errors import GoogleCallError, classify

_refresh_lock = threading.Lock()


def _refresh(creds) -> None:
    from google.auth.transport.requests import Request

    creds.refresh(Request())


def _load():
    try:
        return credentials.load_credentials()
    except GoogleCallError:
        raise
    except Exception as exc:  # noqa: BLE001 - a broken key file surfaces here
        if getattr(exc, "code", None) == "no_key":
            raise GoogleCallError("no_key", "No Google key is connected") from exc
        raise GoogleCallError("key_invalid", f"{type(exc).__name__}: {exc}") from exc


def bearer_token() -> str:
    """A valid access token for HTTP calls to Vertex. Not journaled (free)."""
    if not credentials.has_key():
        raise GoogleCallError("no_key", "No Google key is connected")
    creds = _load()
    with _refresh_lock:
        if not creds.valid:
            try:
                _refresh(creds)
            except Exception as exc:  # noqa: BLE001
                raise classify(exc) from exc
        return str(creds.token)


async def check_token(*, purpose: str = "connection_check") -> None:
    """Fetch a fresh access token once. Raises ``GoogleCallError`` on failure."""
    is_stub = get_config().stub
    if not credentials.has_key():
        raise GoogleCallError("no_key", "No Google key is connected")
    call_id = journal.start_call(kind="token", purpose=purpose, request={"scopes": list(credentials.SCOPES)},
                                 stub=is_stub)
    try:
        if is_stub:
            await asyncio.sleep(stub.delay())
        else:
            creds = _load()

            def refresh() -> None:
                with _refresh_lock:
                    _refresh(creds)

            await asyncio.to_thread(refresh)
    except asyncio.CancelledError:
        journal.finish_call(call_id, status="cancelled", cost_usd=0)
        raise
    except Exception as exc:  # noqa: BLE001
        err = classify(exc)
        journal.finish_call(call_id, status="error", error_code=err.code, error_text=err.raw,
                            http_status=err.http_status, cost_usd=0)
        err.call_ids = [call_id]
        raise err from exc
    journal.finish_call(call_id, status="success", response={"token": "issued"}, cost_usd=0)
