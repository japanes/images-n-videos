"""Stand-in for the app and stt images in the updater end-to-end test.

Environment (baked into the image at build time):
  FAKE_ROLE     app | stt
  FAKE_VERSION  version this image pretends to be
  FAKE_PORT     port to listen on
  FAKE_BROKEN   1 = write to the database and then crash (a bad release)
"""

import json
import os
import signal
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROLE = os.environ.get("FAKE_ROLE", "app")
VERSION = os.environ.get("FAKE_VERSION", "0.0.0")
PORT = int(os.environ.get("FAKE_PORT", "8787"))
BROKEN = os.environ.get("FAKE_BROKEN") == "1"
DATA = os.environ.get("VF_DATA_DIR", "/data")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(line):
    with open(os.path.join(DATA, "e2e-app.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{now()} {line}\n")


def boot():
    """Imitate a schema migration: every start of the app writes to the database."""
    conn = sqlite3.connect(os.path.join(DATA, "app.db"), timeout=30)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS boot (v TEXT, at TEXT)")
        conn.execute("INSERT INTO boot VALUES (?, ?)", (f"booted {VERSION}", now()))
        conn.commit()
    finally:
        conn.close()


def read_token():
    try:
        with open(os.path.join(DATA, "update", "token"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self.send_json(200, {"ok": True, "version": VERSION, "role": ROLE})
        if ROLE == "app" and self.path == "/api/models":
            return self.send_json(200, {"items": []})
        if ROLE == "app" and self.path == "/":
            body = f"<!doctype html><title>fake {VERSION}</title>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return self.send_json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if ROLE != "app" or not self.path.startswith("/api/internal/updates/"):
            return self.send_json(404, {"ok": False})
        token = read_token()
        if not token or self.headers.get("X-VF-Token") != token:
            log(f"{self.path} rejected: bad token")
            return self.send_json(401, {"ok": False})
        body = json.loads(raw or b"{}")
        if self.path.endswith("/prepare"):
            log(f"prepare {body.get('target_version')} ttl={body.get('ttl_seconds')} "
                f"from={VERSION}")
            return self.send_json(200, {"ok": True})
        if self.path.endswith("/resume"):
            log(f"resume from={VERSION}")
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"ok": False})


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # PID 1 ignores it otherwise
    if ROLE == "app":
        boot()
        if BROKEN:
            print(f"fake app {VERSION}: broken on purpose", flush=True)
            sys.exit(1)
    print(f"fake {ROLE} {VERSION} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
