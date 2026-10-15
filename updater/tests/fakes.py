"""Test doubles: fake clock, fake HTTP, fake docker, helpers to build an engine."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

from vf_updater import config
from vf_updater.docker_ops import DockerError
from vf_updater.engine import Engine
from vf_updater.http_util import HttpError, HttpResponse
from vf_updater.store import Store

PREFIX = "ghcr.io/japanes/images-n-videos"
# Fixed "now" for tests: 12:00 UTC is outside the default auto-update window.
DEFAULT_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc).timestamp()


def digest(char: str) -> str:
    return "sha256:" + char * 64


def make_manifest(version, prerelease=False, min_from=None, prefix=PREFIX):
    data = {
        "version": version,
        "prerelease": prerelease,
        "images": {svc: f"{prefix}/{svc}@{digest(c)}"
                   for svc, c in (("app", "a"), ("render", "b"), ("stt", "c"),
                                  ("updater", "d"))},
    }
    if min_from:
        data["min_upgrade_from"] = min_from
    return data


def gh_release(version, prerelease=False, with_manifest=True, draft=False, body="notes"):
    assets = []
    if with_manifest:
        assets.append({"name": "manifest.json",
                       "browser_download_url": f"https://dl.test/{version}/manifest.json"})
    return {
        "tag_name": f"v{version}",
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-10-01T10:00:00Z",
        "body": body,
        "html_url": f"https://github.com/japanes/images-n-videos/releases/tag/v{version}",
        "assets": assets,
    }


class Clock:
    def __init__(self, start=None):
        self.now = float(start if start is not None else DEFAULT_NOW)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def wait(self, seconds):
        self.now += seconds
        return False


class FakeHttp:
    """Routes: {(method, url_prefix): handler(method, url, headers, body) -> (status, json|bytes, headers)}."""

    def __init__(self):
        self.routes = []
        self.calls = []
        self.health = {}  # base url -> version or None
        self.app_prepare = [{"ok": True}]
        self.app_reachable = True
        self.app_prepare_status = 200
        self.resume_calls = 0

    def route(self, method, prefix, handler):
        self.routes.insert(0, (method, prefix, handler))

    def __call__(self, method, url, headers=None, body=None, timeout=15, max_bytes=None):
        self.calls.append((method, url, dict(headers or {}), body))
        if url.endswith("/health"):
            base = url[: -len("/health")]
            version = self.health.get(base)
            if version is None:
                raise HttpError(f"{url}: connection refused")
            return _resp(200, {"ok": True, "version": version})
        if url.endswith("/api/internal/updates/prepare"):
            if not self.app_reachable:
                raise HttpError("app down")
            answer = self.app_prepare[0] if len(self.app_prepare) == 1 else self.app_prepare.pop(0)
            return _resp(self.app_prepare_status, answer)
        if url.endswith("/api/internal/updates/resume"):
            self.resume_calls += 1
            return _resp(200, {"ok": True})
        for m, prefix, handler in self.routes:
            if m == method and url.startswith(prefix):
                status, payload, hdrs = handler(method, url, headers or {}, body)
                return _resp(status, payload, hdrs)
        return _resp(404, {"message": "Not Found"})


def _resp(status, payload, headers=None):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return HttpResponse(status, headers or {}, body)


class FakeDocker:
    def __init__(self, http: FakeHttp, cfg):
        self.http = http
        self.cfg = cfg
        self.images = {}  # ref -> image id
        self.containers = []  # dicts: id, name, service, state, image
        self.helpers = []  # (image, args)
        self.compose_calls = []  # (project, file, env)
        self.pulls = []
        self.tags = []
        self.fail_pull = set()
        self.helper_state = None
        self.broken_versions = set()  # app never becomes healthy
        self.failing_compose_versions = set()
        self.stopped = []
        self.files_in_images = {}

    def image_exists(self, ref):
        return ref in self.images

    def image_id(self, ref):
        return self.images.get(ref)

    def pull(self, ref, timeout=3600):
        if ref in self.fail_pull:
            raise DockerError(f"pull access denied for {ref}")
        self.pulls.append(ref)
        self.images[ref] = "id-" + ref

    def tag(self, src, dst):
        self.tags.append((src, dst))
        self.images[dst] = self.images.get(src, "id-" + src)

    def read_file_from_image(self, image, path):
        if image not in self.files_in_images:
            raise DockerError(f"no such image {image}")
        return self.files_in_images[image]

    def project_containers(self, project):
        return [dict(c) for c in self.containers]

    def container_state(self, name):
        if name == self.cfg.helper_name:
            return self.helper_state
        for c in self.containers:
            if c["name"] == name or c["id"] == name:
                return c["state"]
        return None

    def container_image_id(self, name):
        for c in self.containers:
            if c["id"] == name:
                return "sha256:own"
        return None

    def remove_container(self, name):
        if name == self.cfg.helper_name:
            self.helper_state = None

    def stop_containers(self, ids, timeout_s=30):
        self.stopped.extend(ids)
        for c in self.containers:
            if c["id"] in ids:
                c["state"] = "exited"

    def run_detached(self, image, args, name, network, volume, env, socket=None):
        self.helpers.append((image, list(args), dict(env)))
        return "helper-id"

    def compose_up(self, project, compose_file, env, timeout=3600):
        version = env["VF_VERSION"]
        self.compose_calls.append((project, compose_file, dict(env)))
        if version in self.failing_compose_versions:
            raise DockerError("compose up failed")
        self.containers = [
            {"id": f"{svc}-{version}", "name": f"{project}-{svc}-1", "service": svc,
             "state": "running", "image": self.cfg.image(svc, version)}
            for svc in ("app", "render", "stt", "updater")
        ]
        self.http.health[self.cfg.updater_url] = version
        self.http.health[self.cfg.app_url] = None if version in self.broken_versions else version


class Env:
    """A temp /data dir plus an engine wired to fakes."""

    def __init__(self, version="0.1.0", env=None, clock=None):
        self.tmp = tempfile.mkdtemp(prefix="vf-updater-test-",
                                    dir=os.environ.get("VF_TEST_TMP") or None)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.stack_src = os.path.join(self.tmp, "stack.yml")
        with open(self.stack_src, "w") as fh:
            fh.write("services: {}\n")
        self.clock = clock or Clock()
        self.http = FakeHttp()
        self.base_env = {"VF_DATA_DIR": self.data, "VF_STACK_FILE": self.stack_src,
                         "VF_PREPARE_TIMEOUT": "600", "VF_VERIFY_TIMEOUT": "60"}
        self.base_env.update(env or {})
        self.cfg = self.make_cfg(version)
        self.store = Store(self.data)
        self.store.ensure_dirs()
        self.store.ensure_token()
        self.docker = FakeDocker(self.http, self.cfg)
        self.releases_list = []
        self.manifests = {}
        self.http.route("GET", "https://api.github.com/repos/japanes/images-n-videos/releases",
                        self._releases_handler)
        self.http.route("GET", "https://dl.test/", self._manifest_handler)
        self.engine = self.make_engine(version)

    def make_cfg(self, version):
        env = dict(self.base_env)
        env["VF_VERSION"] = version
        return config.load(env)

    def make_engine(self, version):
        cfg = self.make_cfg(version)
        self.docker.cfg = cfg
        return Engine(cfg, store=Store(self.data), docker=self.docker, http=self.http,
                      clock=self.clock, sleep=self.clock.sleep, wait=self.clock.wait,
                      log=lambda m: None)

    def add_release(self, version, prerelease=False, min_from=None, with_manifest=True):
        self.releases_list.insert(0, gh_release(version, prerelease, with_manifest))
        self.manifests[version] = make_manifest(version, prerelease, min_from)

    def _releases_handler(self, method, url, headers, body):
        path = url.split("?", 1)[0]
        if "/tags/v" in path:
            tag = path.rsplit("/tags/", 1)[1]
            for rel in self.releases_list:
                if rel["tag_name"] == tag:
                    return 200, rel, {}
            return 404, {"message": "Not Found"}, {}
        return 200, self.releases_list, {"ETag": '"e1"'}

    def _manifest_handler(self, method, url, headers, body):
        version = url.split("/")[3]
        return 200, self.manifests[version], {}

    def install_state(self, version):
        self.store.write_state(installed_version=version)
        self.docker.compose_up(self.cfg.project, "x", {"VF_VERSION": version})
        for svc in ("app", "render", "stt", "updater"):
            self.docker.images[self.cfg.image(svc, version)] = f"id-{svc}-{version}"

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
