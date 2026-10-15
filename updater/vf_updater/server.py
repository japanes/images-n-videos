"""HTTP API of the updater (internal port 8080, never published to the host).

Every route except GET /health needs the header X-VF-Token with the content
of /data/update/token. Only the app backend knows it; the browser never does.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .app_client import TOKEN_HEADER
from .engine import BadRequest, Conflict, NotFound

MAX_BODY = 64 * 1024


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "vf-updater"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet access log, never logs headers
            pass

        def _send(self, status: int, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str):
            self._send(status, {"ok": False, "error": code, "message": message})

        def _authorized(self) -> bool:
            if engine.store.check_token(self.headers.get(TOKEN_HEADER)):
                return True
            self._error(401, "unauthorized", "missing or wrong X-VF-Token")
            return False

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("bad Content-Length") from None
            if length > MAX_BODY:
                raise BadRequest("request body is too large")
            raw = self.rfile.read(length) if length else b""
            if not raw.strip():
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                raise BadRequest("body must be JSON") from None
            if not isinstance(data, dict):
                raise BadRequest("body must be a JSON object")
            return data

        def _route(self, method: str):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if method == "GET" and path == "/health":
                return self._send(200, {"ok": True, "version": engine.cfg.version,
                                        "state": engine.status()["state"]})
            routes = {
                ("GET", "/status"): self._status,
                ("POST", "/check"): self._check,
                ("POST", "/install"): self._install,
                ("POST", "/settings"): self._settings,
                ("POST", "/stop"): self._stop,
                ("GET", "/history"): self._history,
            }
            handler = routes.get((method, path))
            if handler is None:
                known_paths = {p for (_, p) in routes} | {"/health"}
                if path in known_paths:
                    return self._error(405, "method_not_allowed", f"{method} is not allowed")
                return self._error(404, "not_found", "no such endpoint")
            if not self._authorized():
                return None
            try:
                return handler()
            except BadRequest as exc:
                return self._error(400, "bad_request", str(exc))
            except NotFound as exc:
                return self._error(404, "not_found", str(exc))
            except Conflict as exc:
                return self._error(409, "conflict", str(exc))
            except Exception as exc:  # noqa: BLE001
                engine.log(f"request {method} {path} failed: {exc}")
                return self._error(500, "internal", str(exc)[:500])

        def _status(self):
            self._send(200, engine.status())

        def _check(self):
            self._body()
            self._send(200, engine.check(manual=True))

        def _install(self):
            data = self._body()
            op = engine.start_install(data.get("version"), force=data.get("force", False))
            self._send(202, {"ok": True, "operation": op})

        def _settings(self):
            data = self._body()
            self._send(200, engine.update_settings(data))

        def _stop(self):
            self._body()
            engine.request_stop()
            self._send(202, {"ok": True})

        def _history(self):
            self._send(200, {"items": engine.history()})

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def do_PUT(self):  # noqa: N802
            self._route("PUT")

        def do_DELETE(self):  # noqa: N802
            self._route("DELETE")

    return Handler


def make_server(engine, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(engine))
    server.daemon_threads = True
    return server


def serve(engine, stop_event: threading.Event | None = None):
    """Run the API and the scheduler until stop_event is set or the process ends."""
    stop_event = stop_event or threading.Event()
    engine.store.ensure_dirs()
    engine.store.ensure_token()
    server = make_server(engine, engine.cfg.listen_host, engine.cfg.listen_port)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    engine.log(f"version {engine.cfg.version} listening on :{engine.cfg.listen_port}"
               + (" (developer mode: no installs)" if engine.cfg.dev else ""))
    try:
        while not stop_event.is_set():
            try:
                engine.tick()
            except Exception as exc:  # noqa: BLE001
                engine.log(f"scheduler error: {exc}")
            stop_event.wait(30)
    finally:
        server.shutdown()
        server.server_close()
