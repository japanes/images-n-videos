"""Update engine.

Two roles share this code:
* the long-running updater service (checks releases, prepares and pulls an
  update, starts a helper, reconciles the stack on start, runs auto updates);
* a one-off helper container started from the TARGET version's updater image
  (`install`, `apply`, `rollback`, `stop`). The helper survives the
  recreation of the updater service, switches the stack with docker compose,
  verifies it and rolls back on failure.

The helper command line and /data/update/op.json are a contract between
versions: newer versions must keep accepting them and ignore unknown fields.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta

from . import backup, versions
from . import manifest as manifest_mod
from .app_client import AppClient, AppUnreachable, health_version
from .docker_ops import Docker, DockerError
from .http_util import request
from .releases import ReleaseClient, ReleaseError, filter_available
from .store import Store, parse_utc, utc_now

ACTIVE_STATES = ("preparing", "backing_up", "pulling", "applying", "verifying", "rolling_back")
STACK_SERVICES = ("app", "render", "stt", "updater")
HELPER_STALE_SECONDS = 90
HEARTBEAT_SECONDS = 15
RECONCILE_RETRY_SECONDS = 300
RECONCILE_AFTER_OP_SECONDS = 60
APPLY_GUARD_SECONDS = 120
AUTO_WINDOW_SECONDS = 6 * 3600
AUTO_RETRY_SECONDS = 1800
PREPARE_POLL_SECONDS = 15
APP_UNREACHABLE_GRACE_SECONDS = 30
CHECK_RETRY_SECONDS = 1800
OP_FILE = "/data/update/op.json"


class UpdateError(Exception):
    pass


class Conflict(Exception):
    """Maps to HTTP 409."""


class NotFound(Exception):
    """Maps to HTTP 404."""


class BadRequest(Exception):
    """Maps to HTTP 400."""


def _service_order(images: dict) -> list:
    keys = sorted(k for k in images if k != "updater")
    if "updater" in images:
        keys.append("updater")
    return keys


class Heartbeat:
    """Keeps op.heartbeat_at fresh while a helper works."""

    def __init__(self, store: Store, interval: float = HEARTBEAT_SECONDS):
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.store.update_op(heartbeat_at=utc_now())
            except Exception:
                pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)
        return False


class Engine:
    def __init__(self, cfg, store=None, docker=None, releases=None, app=None, http=request,
                 clock=time.time, sleep=time.sleep, wait=None, log=None):
        self.cfg = cfg
        self.store = store or Store(cfg.data_dir)
        self.docker = docker or Docker()
        self.http = http
        self.releases = releases or ReleaseClient(cfg, self.store, http=http, clock=clock)
        self.app = app or AppClient(cfg, self.store, http=http)
        self.clock = clock
        self.sleep = sleep
        self._force = threading.Event()
        self.wait = wait or (lambda seconds: self._force.wait(seconds))
        self.log = log or (lambda message: print(f"[updater] {message}", flush=True))
        self._op_lock = threading.RLock()
        self._check_lock = threading.Lock()
        self._worker = None
        self.checking = False
        self.reconcile_due = 0.0  # epoch seconds; None = nothing pending
        self.reconcile_error = None
        self._last_apply_at = 0.0
        self._last_check_log = None

    # ------------------------------------------------------------------ status
    def installed_version(self):
        return self.store.read_state().get("installed_version")

    def base_version(self) -> str:
        return self.installed_version() or self.cfg.version

    def status(self) -> dict:
        settings = self.store.read_settings()
        check = self.store.read_check()
        state = self.store.read_state()
        op = self.store.read_op()
        installed = state.get("installed_version")
        base = installed or self.cfg.version
        failed = set(state.get("failed_versions") or [])
        manifests = check.get("manifests") or {}
        available = []
        for rel in filter_available(check.get("releases") or [], base, settings["channel"]):
            man = manifests.get(rel["version"])
            min_from = man.get("min_upgrade_from") if isinstance(man, dict) else None
            installable = bool(rel.get("manifest_url"))
            if installable and isinstance(man, dict):
                installable = manifest_mod.can_upgrade_from(man, base)
            available.append({
                "version": rel["version"],
                "prerelease": rel.get("prerelease", False),
                "published_at": rel.get("published_at"),
                "notes_md": rel.get("notes_md", ""),
                "html_url": rel.get("html_url"),
                "installable": installable,
                "min_upgrade_from": min_from,
                "failed_before": rel["version"] in failed,
            })
        shown_op = None
        if op and (op.get("active") or op.get("kind") == "install"):
            shown_op = op
        if self.checking:
            current_state = "checking"
        elif shown_op:
            current_state = shown_op.get("state") or "idle"
        else:
            current_state = "idle"
        error = None
        if shown_op and shown_op.get("state") == "failed":
            error = shown_op.get("error")
        elif not shown_op or not shown_op.get("active"):
            error = self.reconcile_error
        return {
            "current_version": self.cfg.version,
            "installed_version": installed,
            "channel": settings["channel"],
            "auto": settings["auto"],
            "time": settings["time"],
            "tz": settings["tz"],
            "dev": self.cfg.dev,
            "last_check_at": check.get("last_check_at"),
            "last_check_error": check.get("last_check_error"),
            "available": available,
            "state": current_state,
            "step_log": (shown_op or {}).get("step_log") or [],
            "error": error,
            "operation": _public_op(shown_op),
        }

    def history(self, limit: int = 100) -> list:
        return self.store.read_history(limit)

    def update_settings(self, patch: dict) -> dict:
        try:
            self.store.update_settings(patch)
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
        return self.status()

    # ------------------------------------------------------------------- check
    def check(self, manual: bool = True) -> dict:
        with self._check_lock:
            self.checking = True
            try:
                self.releases.fetch(manual=manual)
                self._prefetch_manifests()
            except ReleaseError as exc:
                if str(exc) != self._last_check_log:
                    self.log(f"release check failed: {exc}")
                self._last_check_log = str(exc)
            else:
                self._last_check_log = None
            finally:
                self.checking = False
        return self.status()

    def _prefetch_manifests(self):
        settings = self.store.read_settings()
        for rel in filter_available(self.releases.releases(), self.base_version(),
                                    settings["channel"])[:3]:
            if not rel.get("manifest_url"):
                continue
            try:
                self.releases.get_manifest(rel)
            except ReleaseError as exc:
                self.log(f"manifest of {rel['version']}: {exc}")

    # ------------------------------------------------------- install (updater)
    def start_install(self, version, force: bool = False, source: str = "manual") -> dict:
        if not isinstance(version, str) or not versions.is_valid(version):
            raise BadRequest("version must look like 1.2.3")
        if not isinstance(force, bool):
            raise BadRequest("force must be true or false")
        version = versions.normalize(version)
        if self.cfg.dev:
            raise Conflict("updates are turned off in developer mode")
        with self._op_lock:
            op = self.store.read_op()
            if op and op.get("active"):
                if (force and op.get("kind") == "install" and op.get("to") == version
                        and op.get("state") == "preparing"):
                    self._force.set()
                    return _public_op(self.store.op_log("install anyway was requested",
                                                        force=True))
                raise Conflict("another update is already running")
            base = self.base_version()
            if versions.parse(version) <= versions.parse(base):
                raise Conflict(f"version {version} is not newer than {base}")
            rel = self.releases.find(version)
            if not rel:
                try:
                    self.releases.fetch(manual=True)
                except ReleaseError as exc:
                    raise Conflict(f"cannot check releases: {exc}") from None
                rel = self.releases.find(version)
            if not rel:
                raise NotFound(f"release {version} not found")
            channel = self.store.read_settings()["channel"]
            if not versions.channel_allows(channel, version, rel.get("prerelease")):
                raise Conflict(f"{version} is a test version; switch to the beta channel first")
            if self.docker.container_state(self.cfg.helper_name) == "running":
                raise Conflict("another update is already running")
            now = utc_now()
            op = {
                "id": uuid.uuid4().hex,
                "kind": "install",
                "source": source,
                "from": base,
                "to": version,
                "force": force,
                "state": "preparing",
                "active": True,
                "runner": "updater",
                "started_at": now,
                "finished_at": None,
                "heartbeat_at": now,
                "step_log": [],
                "busy": [],
                "error": None,
                "backup_file": None,
                "helper_container": None,
            }
            self.store.write_op(op)
            self._force.clear()
            if force:
                self._force.set()
            self._worker = threading.Thread(target=self._run_install, args=(op["id"], rel),
                                            name="install", daemon=True)
            self._worker.start()
            return _public_op(op)

    def _oplog(self, message: str, **fields):
        self.log(message)
        return self.store.op_log(message, **fields)

    def _run_install(self, op_id: str, rel: dict):
        version = rel["version"]
        paused = False
        try:
            op = self.store.read_op() or {}
            self._oplog(f"checking release {version}", state="preparing")
            man = self.releases.get_manifest(rel)
            if not manifest_mod.can_upgrade_from(man, op.get("from")):
                raise UpdateError(
                    f"version {version} can be installed only from {man['min_upgrade_from']} "
                    "or newer")
            paused = True
            self._prepare_app(version)
            self._oplog("saving a copy of the database", state="backing_up")
            backup_file = backup.create(self.store.db_path, self.store.backups_dir,
                                        op.get("from") or "unknown")
            if backup_file:
                removed = backup.rotate(self.store.backups_dir, protect=[backup_file])
                self._oplog(f"database copy saved: {os.path.basename(backup_file)}",
                            backup_file=backup_file)
                for path in removed:
                    self.log(f"old backup removed: {path}")
            else:
                self._oplog("no database yet, nothing to copy")
            self._oplog("downloading the new version", state="pulling")
            for svc in _service_order(man["images"]):
                ref = man["images"][svc]
                self._oplog(f"downloading {svc}")
                self.docker.pull(ref)
                self.docker.tag(ref, self.cfg.image(svc, version))
            self._oplog("switching to the new version", state="applying", runner="helper")
            self._start_helper(version, ["install", "--op", OP_FILE])
        except Exception as exc:  # noqa: BLE001 - every failure must end the operation
            self._abort(op_id, _err(exc), paused)

    def _prepare_app(self, version: str):
        self._oplog("asking the app to finish current work", state="preparing")
        deadline = self.clock() + self.cfg.prepare_timeout
        unreachable_since = None
        last_busy = None
        while True:
            try:
                res = self.app.prepare(version)
            except AppUnreachable as exc:
                now = self.clock()
                if unreachable_since is None:
                    unreachable_since = now
                    self._oplog(f"the app does not answer ({exc}), waiting a bit")
                if now - unreachable_since >= APP_UNREACHABLE_GRACE_SECONDS:
                    self._oplog("the app still does not answer, continuing without it")
                    return
                self.sleep(5)
                continue
            unreachable_since = None
            if res["ok"]:
                self._oplog("the app is ready for the update", busy=[])
                return
            busy = res["busy"]
            if busy != last_busy:
                titles = ", ".join(b["title"] or b["kind"] for b in busy) or "unknown"
                self._oplog(f"waiting for running jobs: {titles}", busy=busy)
                last_busy = busy
            if self._force.is_set():
                self._oplog("installing anyway, running jobs will be interrupted")
                return
            if self.clock() >= deadline:
                minutes = max(1, self.cfg.prepare_timeout // 60)
                raise UpdateError(f"the app is still busy after {minutes} min; "
                                  "update postponed")
            self.wait(PREPARE_POLL_SECONDS)

    def _abort(self, op_id: str, message: str, paused: bool):
        self.log(f"update aborted: {message}")
        if paused:
            self.app.resume()
        op = self.store.read_op() or {}
        if op.get("id") != op_id:
            return
        self._finish(op, "failed", message)

    def _finish(self, op: dict, result: str, error=None):
        """End an operation. result: success | failed | rolled_back."""
        state = "done" if result == "success" else "failed"
        finished = utc_now()
        op = self.store.op_log(
            "finished" if result == "success" else f"finished with an error: {error}",
            state=state, active=False, finished_at=finished, error=error, result=result)
        if op.get("kind") == "install" or (op.get("kind") == "apply"
                                           and op.get("purpose") == "fresh"):
            self.store.append_history({
                "op_id": op.get("id"),
                "kind": op.get("kind"),
                "source": op.get("source"),
                "version_from": op.get("from"),
                "version_to": op.get("to"),
                "started_at": op.get("started_at"),
                "finished_at": finished,
                "result": result,
                "error": error,
                "backup_file": op.get("backup_file"),
            })
        return op

    def _start_helper(self, image_version: str, args: list):
        name = self.cfg.helper_name
        current = self.docker.container_state(name)
        if current == "running":
            raise UpdateError("another update helper is already running")
        if current:
            self.docker.remove_container(name)
        env = self.cfg.passthrough_env()
        env.update({
            "VF_PROJECT": self.cfg.project,
            "VF_DATA_VOLUME": self.cfg.data_volume,
            "VF_IMAGE_PREFIX": self.cfg.image_prefix,
        })
        self._last_apply_at = self.clock()
        self.docker.run_detached(self.cfg.image("updater", image_version), args, name,
                                 self.cfg.network, self.cfg.data_volume, env)

    # ------------------------------------------------------------ stop (updater)
    def request_stop(self):
        if self.cfg.dev:
            raise Conflict("stopping from here is turned off in developer mode")
        op = self.store.read_op()
        if op and op.get("active"):
            raise Conflict("an update is running, try again when it ends")
        version = self.cfg.version
        self._ensure_own_image_tag()
        self._start_helper(version, ["stop"])

    # ------------------------------------------------------------- helper side
    def helper_install(self) -> int:
        op = self.store.read_op()
        if not op or op.get("kind") != "install" or not op.get("active"):
            self.log("no install operation to run")
            return 2
        if op.get("to") != self.cfg.version:
            self._rollback(op, f"helper version {self.cfg.version} does not match {op.get('to')}")
            return 1
        with Heartbeat(self.store):
            try:
                self._oplog(f"starting version {op['to']}", state="applying",
                            runner="helper", helper_container=socket.gethostname())
                self._apply_stack(op["to"])
                self._oplog("checking that the new version works", state="verifying")
                self._verify(op["to"])
            except Exception as exc:  # noqa: BLE001
                self._rollback(self.store.read_op() or op, _err(exc))
                return 1
            now = utc_now()
            state = self.store.read_state()
            self.store.write_state(installed_version=op["to"], previous_version=op.get("from"),
                                   updated_at=now,
                                   failed_versions=[v for v in state.get("failed_versions") or []
                                                    if v != op["to"]])
            self._finish(self.store.read_op() or op, "success")
        return 0

    def helper_rollback(self) -> int:
        op = self.store.read_op()
        if not op or not op.get("active"):
            self.log("no operation to roll back")
            return 2
        with Heartbeat(self.store):
            self.store.update_op(runner="helper", helper_container=socket.gethostname())
            self._rollback(op, op.get("error") or "the update was interrupted")
        return 1

    def _rollback(self, op: dict, reason: str):
        from_version = op.get("from")
        self._oplog(f"the new version failed: {reason}; going back to {from_version}",
                    state="rolling_back")
        try:
            if not from_version:
                raise UpdateError("previous version is unknown")
            app_ids = [c["id"] for c in self.docker.project_containers(self.cfg.project)
                       if c.get("service") == "app" and c.get("state") in ("running",
                                                                            "restarting")]
            if app_ids:
                self._oplog("stopping the new app")
                self.docker.stop_containers(app_ids)
            if op.get("backup_file"):
                backup.restore(op["backup_file"], self.store.db_path)
                self._oplog("database restored from the copy")
            self._oplog(f"starting version {from_version} again")
            self._apply_stack(from_version)
            self._verify(from_version)
        except Exception as exc:  # noqa: BLE001
            message = f"{reason}. Going back to {from_version} also failed: {_err(exc)}"
            self._mark_failed_version(op.get("to"))
            self._finish(self.store.read_op() or op, "failed", message)
            return
        self.app.resume()
        self._mark_failed_version(op.get("to"))
        self._finish(self.store.read_op() or op, "rolled_back",
                     f"{reason}. Version {from_version} was restored.")

    def _mark_failed_version(self, version):
        if not version:
            return
        state = self.store.read_state()
        failed = list(state.get("failed_versions") or [])
        if version not in failed:
            failed.append(version)
            self.store.write_state(failed_versions=failed[-20:])

    def helper_apply(self) -> int:
        op = self.store.read_op()
        if not op or op.get("kind") != "apply" or not op.get("active"):
            self.log("no apply operation to run")
            return 2
        target = op.get("to")
        with Heartbeat(self.store):
            try:
                if target != self.cfg.version:
                    raise UpdateError(f"helper {self.cfg.version} cannot start {target}")
                self.store.update_op(runner="helper", helper_container=socket.gethostname())
                images = op.get("images") or {}
                missing = [s for s in STACK_SERVICES
                           if not self.docker.image_exists(self.cfg.image(s, target))]
                if missing:
                    self._oplog("downloading: " + ", ".join(missing), state="pulling")
                    for svc in missing:
                        ref = images.get(svc) or self.cfg.image(svc, target)
                        self.docker.pull(ref)
                        if ref != self.cfg.image(svc, target):
                            self.docker.tag(ref, self.cfg.image(svc, target))
                self._oplog(f"starting version {target}", state="applying")
                self._apply_stack(target)
                self._oplog("checking that everything started", state="verifying")
                self._verify(target)
            except Exception as exc:  # noqa: BLE001
                self._finish(self.store.read_op() or op, "failed", _err(exc))
                return 1
            if op.get("purpose") == "fresh":
                self.store.write_state(installed_version=target, installed_at=utc_now())
            self._finish(self.store.read_op() or op, "success")
        return 0

    def helper_stop(self) -> int:
        containers = self.docker.project_containers(self.cfg.project)
        running = [c for c in containers if c.get("state") in ("running", "restarting")]
        first = [c["id"] for c in running if c.get("service") != "updater"]
        last = [c["id"] for c in running if c.get("service") == "updater"]
        self.docker.stop_containers(first)
        self.docker.stop_containers(last)
        self.log(f"stopped {len(first) + len(last)} containers")
        return 0

    def _apply_stack(self, version: str):
        stack_file = self.store.stack_file(version)
        os.makedirs(os.path.dirname(stack_file), exist_ok=True)
        if version == self.cfg.version and os.path.exists(self.cfg.stack_file):
            with open(self.cfg.stack_file, encoding="utf-8") as fh:
                content = fh.read()
            _write_text(stack_file, content)
        elif not os.path.exists(stack_file):
            content = self.docker.read_file_from_image(self.cfg.image("updater", version),
                                                       "/stack/compose.yml")
            _write_text(stack_file, content)
        env = self.cfg.passthrough_env()
        env.update({
            "VF_VERSION": version,
            "VF_PROJECT": self.cfg.project,
            "VF_DATA_VOLUME": self.cfg.data_volume,
            "VF_IMAGE_PREFIX": self.cfg.image_prefix,
        })
        self.docker.compose_up(self.cfg.project, stack_file, env)

    def _verify(self, version: str):
        deadline = self.clock() + self.cfg.verify_timeout
        app_v = upd_v = None
        while True:
            app_v = health_version(self.cfg.app_url, http=self.http)
            upd_v = health_version(self.cfg.updater_url, http=self.http)
            if app_v == version and upd_v == version:
                self._oplog(f"version {version} is running")
                return
            if self.clock() >= deadline:
                raise UpdateError(
                    f"version {version} did not start within {self.cfg.verify_timeout} s "
                    f"(app: {app_v or 'no answer'}, updater: {upd_v or 'no answer'})")
            self.sleep(3)

    # -------------------------------------------------------------- reconcile
    def reconcile(self):
        """Bring the stack to the installed version. Called on start and on retries."""
        if self.cfg.dev:
            return
        op = self.store.read_op()
        if op and op.get("active"):
            self.recover_stale_op(op)
            # Look at the stack again once the operation is over (it may have failed
            # after this updater was started by it).
            if self.reconcile_due is None:
                self.reconcile_due = self.clock() + RECONCILE_AFTER_OP_SECONDS
            return
        own = self.cfg.version
        if own == versions.DEV_VERSION:
            self.log("development build: not managing the stack")
            return
        installed = self.installed_version()
        if not installed:
            self.log(f"first start: installing version {own}")
            self._start_apply(own, "fresh", None)
        elif installed != own:
            self.log(f"installed version is {installed}, this updater is {own}: handing over")
            self._start_apply(installed, "handover", installed)
        elif self._stack_needs_apply(own):
            self.log("some services are not running: starting them")
            self._start_apply(own, "ensure", installed)

    def _stack_needs_apply(self, version: str) -> bool:
        by_service = {}
        for c in self.docker.project_containers(self.cfg.project):
            svc = c.get("service")
            if svc and (svc not in by_service or c.get("state") == "running"):
                by_service[svc] = c
        for svc in STACK_SERVICES:
            c = by_service.get(svc)
            if not c or c.get("state") != "running":
                return True
            if c.get("image") != self.cfg.image(svc, version):
                return True
        return False

    def _ensure_own_image_tag(self):
        ref = self.cfg.image("updater", self.cfg.version)
        if self.docker.image_exists(ref):
            return
        for c in self.docker.project_containers(self.cfg.project):
            if c.get("service") == "updater" and c.get("state") == "running":
                image_id = self.docker.container_image_id(c["id"])
                if image_id:
                    self.docker.tag(image_id, ref)
                    return
        raise UpdateError(f"cannot find the image of this updater to tag it as {ref}")

    def _start_apply(self, version: str, purpose: str, installed):
        now = self.clock()
        if now - self._last_apply_at < APPLY_GUARD_SECONDS:
            self.reconcile_due = self._last_apply_at + APPLY_GUARD_SECONDS
            return
        updater_ref = self.cfg.image("updater", version)
        if version == self.cfg.version:
            self._ensure_own_image_tag()
        images = None
        if purpose == "fresh" or not self.docker.image_exists(updater_ref):
            try:
                rel = self.releases.fetch_tag(version)
                images = self.releases.get_manifest(rel)["images"]
            except ReleaseError as exc:
                self.log(f"no manifest for {version} ({exc}), will pull by tag")
        if not self.docker.image_exists(updater_ref):
            ref = (images or {}).get("updater") or updater_ref
            try:
                self.docker.pull(ref)
                if ref != updater_ref:
                    self.docker.tag(ref, updater_ref)
            except DockerError as exc:
                raise UpdateError(f"cannot download version {version}: {exc}") from None
        op = {
            "id": uuid.uuid4().hex,
            "kind": "apply",
            "purpose": purpose,
            "source": "startup",
            "from": installed,
            "to": version,
            "force": False,
            "state": "applying",
            "active": True,
            "runner": "helper",
            "started_at": utc_now(),
            "finished_at": None,
            "heartbeat_at": utc_now(),
            "step_log": [],
            "busy": [],
            "error": None,
            "backup_file": None,
            "images": images,
            "helper_container": None,
        }
        with self._op_lock:
            self.store.write_op(op)
            try:
                self._start_helper(version, ["apply", "--op", OP_FILE])
            except Exception as exc:  # noqa: BLE001
                self._finish(self.store.read_op() or op, "failed", _err(exc))
                raise
        self.reconcile_due = now + RECONCILE_RETRY_SECONDS

    def recover_stale_op(self, op: dict):
        """Handle an operation left active by a process that is gone."""
        if op.get("runner") != "helper":
            if self._worker and self._worker.is_alive():
                return
            self.log("an update was interrupted by a restart")
            self.app.resume()
            self._finish(op, "failed", "the update was interrupted because the updater restarted")
            return
        beat = parse_utc(op.get("heartbeat_at") or op.get("updated_at"))
        if beat and self.clock() - beat.timestamp() < HELPER_STALE_SECONDS:
            return
        if self.docker.container_state(self.cfg.helper_name) == "running":
            return
        self.log(f"update helper is gone (operation {op.get('kind')} {op.get('state')})")
        if op.get("kind") == "install":
            if (op.get("state") != "rolling_back" and self.cfg.version == op.get("to")
                    and health_version(self.cfg.app_url, http=self.http) == op.get("to")):
                state = self.store.read_state()
                self.store.write_state(installed_version=op["to"],
                                       previous_version=op.get("from"), updated_at=utc_now(),
                                       failed_versions=state.get("failed_versions") or [])
                self._finish(op, "success")
                return
            self.store.op_log("the update helper stopped unexpectedly, rolling back",
                              error=op.get("error") or "the update helper stopped unexpectedly",
                              heartbeat_at=utc_now())
            self._ensure_own_image_tag()
            self._start_helper(self.cfg.version, ["rollback", "--op", OP_FILE])
            return
        self._finish(op, "failed", "the update helper stopped unexpectedly")
        self.reconcile_due = self.clock() + RECONCILE_RETRY_SECONDS

    # -------------------------------------------------------------- scheduler
    def tick(self):
        """One scheduler step; the serve loop calls it every 30 seconds."""
        now = self.clock()
        op = self.store.read_op()
        if op and op.get("active"):
            if not self.cfg.dev:
                try:
                    self.recover_stale_op(op)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"recovery failed: {_err(exc)}")
        elif self.reconcile_due is not None and now >= self.reconcile_due:
            try:
                self.reconcile_due = None
                self.reconcile()
                self.reconcile_error = None
            except Exception as exc:  # noqa: BLE001
                self.reconcile_error = _err(exc)
                self.log(f"start-up check failed: {self.reconcile_error}")
                self.reconcile_due = now + RECONCILE_RETRY_SECONDS
        check = self.store.read_check()
        last_call = float(check.get("last_api_call") or 0)
        interval = self.cfg.check_interval
        if check.get("last_check_error"):
            interval = min(interval, CHECK_RETRY_SECONDS)
        if now - last_call >= interval:
            self.check(manual=False)
        try:
            self.maybe_auto_update()
        except Exception as exc:  # noqa: BLE001
            self.log(f"auto update failed to start: {_err(exc)}")

    def maybe_auto_update(self):
        if self.cfg.dev or self.cfg.version == versions.DEV_VERSION:
            return None
        settings = self.store.read_settings()
        if not settings["auto"]:
            return None
        op = self.store.read_op()
        if op and op.get("active"):
            return None
        window = auto_window(self.clock(), settings["time"], settings["tz"])
        if window is None:
            return None
        state = self.store.read_state()
        if not state.get("installed_version"):
            return None
        if state.get("auto_done_window") == window:
            return None
        if self.clock() - float(state.get("auto_last_attempt_at") or 0) < AUTO_RETRY_SECONDS:
            return None
        check = self.store.read_check()
        if self.clock() - float(check.get("last_api_call") or 0) > 3600:
            self.check(manual=False)
            check = self.store.read_check()
        if check.get("last_check_error"):
            return None
        failed = set(state.get("failed_versions") or [])
        candidates = [r for r in filter_available(check.get("releases") or [],
                                                  self.base_version(), settings["channel"])
                      if r["version"] not in failed and r.get("manifest_url")]
        if not candidates:
            self.store.write_state(auto_done_window=window)
            return None
        target = candidates[0]["version"]
        self.store.write_state(auto_last_attempt_at=self.clock())
        self.log(f"auto update to {target}")
        try:
            return self.start_install(target, force=False, source="auto")
        except (Conflict, NotFound, BadRequest) as exc:
            self.log(f"auto update skipped: {exc}")
            return None


def auto_window(epoch: float, hhmm: str, tz_name: str):
    """Window id (local date of the start) when `epoch` is in [time, time+6h), else None."""
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local_now = datetime.fromtimestamp(epoch, tz)
    hour, minute = (int(x) for x in hhmm.split(":"))
    start = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < start:
        start -= timedelta(days=1)
    if (local_now - start).total_seconds() >= AUTO_WINDOW_SECONDS:
        return None
    return start.strftime("%Y-%m-%d")


def _public_op(op):
    if not op:
        return None
    keys = ("id", "kind", "purpose", "source", "from", "to", "force", "state", "active",
            "result", "started_at", "finished_at", "error", "backup_file", "busy")
    return {k: op.get(k) for k in keys}


def _err(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:2000]


def _write_text(path: str, content: str):
    tmp_path = f"{path}.tmp-{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


__all__ = ["Engine", "Conflict", "NotFound", "BadRequest", "UpdateError", "auto_window"]
