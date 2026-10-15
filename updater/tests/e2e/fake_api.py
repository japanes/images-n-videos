"""Helper for the updater end-to-end test.

  serve DIR                       fake GitHub Releases API + release downloads on :8000
  publish DIR VERSION PREFIX DIGESTS [--prerelease] [--no-manifest]
                                  add a release (run on the host, writes into DIR)
  call METHOD PATH [JSON]         call the updater API with the token from /data/update/token
  rows                            print the "boot" rows of /data/app.db as JSON

DIR holds releases.json (GitHub-like list) and manifests/<version>.json.
"""

import hashlib
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_HOST = os.environ.get("E2E_API_HOST", "vf-e2e-api")
UPDATER_URL = os.environ.get("E2E_UPDATER_URL", "http://updater:8080")


def serve(root):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("api:", fmt % args, flush=True)

        def send(self, status, body=b"", headers=None):
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def releases(self):
            try:
                with open(os.path.join(root, "releases.json"), "rb") as fh:
                    return fh.read()
            except OSError:
                return b"[]"

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/releases":
                body = self.releases()
                etag = '"' + hashlib.sha1(body).hexdigest() + '"'
                if self.headers.get("If-None-Match") == etag:
                    return self.send(304, headers={"ETag": etag})
                return self.send(200, body, {"Content-Type": "application/json", "ETag": etag})
            if path.startswith("/releases/tags/"):
                tag = path.rsplit("/", 1)[1]
                for rel in json.loads(self.releases()):
                    if rel.get("tag_name") == tag:
                        return self.send(200, json.dumps(rel).encode(),
                                         {"Content-Type": "application/json"})
                return self.send(404, b'{"message": "Not Found"}')
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "download" and parts[2] == "manifest.json":
                try:
                    with open(os.path.join(root, "manifests", f"{parts[1]}.json"), "rb") as fh:
                        return self.send(200, fh.read(),
                                         {"Content-Type": "application/octet-stream"})
                except OSError:
                    pass
            return self.send(404, b'{"message": "Not Found"}')

    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


def publish(root, version, prefix, digests_file, prerelease, with_manifest):
    os.makedirs(os.path.join(root, "manifests"), exist_ok=True)
    assets = []
    if with_manifest:
        images = {}
        with open(digests_file, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    svc, digest = line.strip().split("=", 1)
                    images[svc] = f"{prefix}/{svc}@{digest}"
        manifest = {"version": version, "prerelease": prerelease, "images": images}
        with open(os.path.join(root, "manifests", f"{version}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        assets.append({"name": "manifest.json",
                       "browser_download_url":
                           f"http://{API_HOST}:8000/download/{version}/manifest.json"})
    path = os.path.join(root, "releases.json")
    try:
        with open(path, encoding="utf-8") as fh:
            releases = json.load(fh)
    except OSError:
        releases = []
    releases = [r for r in releases if r.get("tag_name") != f"v{version}"]
    releases.insert(0, {
        "tag_name": f"v{version}",
        "name": f"Vertex AI Factory {version}",
        "draft": False,
        "prerelease": prerelease,
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": f"Release notes of {version}.",
        "html_url": f"https://example.test/releases/v{version}",
        "assets": assets,
    })
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(releases, fh, indent=2)
    os.replace(tmp, path)


def call(method, path, body=None):
    with open("/data/update/token", encoding="utf-8") as fh:
        token = fh.read().strip()
    data = body.encode() if body else None
    headers = {"X-VF-Token": token}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(UPDATER_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(resp.read().decode())
            return 0
    except urllib.error.HTTPError as exc:
        with exc:
            print(exc.read().decode())
        return 1
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "unreachable", "message": str(exc)}))
        return 2


def rows():
    conn = sqlite3.connect("file:/data/app.db?mode=ro", uri=True)
    try:
        print(json.dumps([r[0] for r in conn.execute("SELECT v FROM boot ORDER BY rowid")]))
    finally:
        conn.close()
    return 0


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "serve":
        serve(argv[1])
        return 0
    if cmd == "publish":
        flags = set(argv[5:])
        publish(argv[1], argv[2], argv[3], argv[4], "--prerelease" in flags,
                "--no-manifest" not in flags)
        return 0
    if cmd == "call":
        return call(argv[1], argv[2], argv[3] if len(argv) > 3 else None)
    if cmd == "rows":
        return rows()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
