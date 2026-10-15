"""Model files on disk: status, verified resumable download with progress, deletion.

Layout under ``<data>/models/``:

- ``<name>/``            a complete model: every file of the pinned revision plus
                         ``.vf-manifest.json``. Only this counts as downloaded.
- ``.partial-<name>/``   a download in progress or interrupted; resumed next time
                         (wiped if it belongs to another revision).
- ``.old-<name>-*``      a replaced model being removed; cleaned up at startup.

A download is moved into place with one atomic rename after every file has the
expected size and digest, so a partial download can never look complete.
"""

from __future__ import annotations

import errno
import hashlib
import http.client
import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import Cancelled, ServiceError
from .registry import ModelFile, ModelSpec

log = logging.getLogger("stt.models")

MANIFEST = ".vf-manifest.json"
REVISION_MARKER = ".vf-revision"
PARTIAL_PREFIX = ".partial-"
OLD_PREFIX = ".old-"
CHUNK_BYTES = 1 << 20
# Keep this much disk free on top of the download itself.
DISK_MARGIN_BYTES = 64 * 1024 * 1024
MAX_ATTEMPTS = 4
USER_AGENT = "vertexai-factory-stt"
# Errors that retrying will not fix.
DISK_ERRNOS = frozenset({errno.ENOSPC, errno.EDQUOT, errno.EROFS, errno.EACCES, errno.EPERM})


def _mb(n: int) -> int:
    return round(n / 1_000_000)


def _new_hasher(f: ModelFile):
    if f.sha256 is not None:
        return hashlib.sha256()
    hasher = hashlib.sha1()  # git blob id, not used for security on its own
    hasher.update(b"blob %d\0" % f.size)
    return hasher


def _expected_digest(f: ModelFile) -> str:
    return f.sha256 if f.sha256 is not None else f.git_sha1  # type: ignore[return-value]


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        raise ServiceError("internal_error", f"could not remove {path.name}")


class _Retryable(Exception):
    """A network hiccup worth another attempt (the next attempt resumes)."""


class DownloadJob:
    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.total_bytes = spec.total_bytes
        self.done_bytes = 0
        self.cancel = threading.Event()
        self.finished = threading.Event()
        self.error: str | None = None
        self.cancelled = False

    @property
    def progress(self) -> float:
        if not self.total_bytes:
            return 0.0
        return round(min(1.0, max(0.0, self.done_bytes / self.total_bytes)), 4)


class ModelStore:
    def __init__(
        self,
        models_dir: Path,
        registry: dict[str, ModelSpec],
        endpoint: str,
        *,
        timeout_s: float = 60.0,
        retry_delay_s: float = 2.0,
    ) -> None:
        self.models_dir = models_dir
        self.registry = registry
        self.endpoint = endpoint.rstrip("/")
        self.timeout_s = timeout_s
        self.retry_delay_s = retry_delay_s
        self._lock = threading.Lock()
        self._jobs: dict[str, DownloadJob] = {}
        self._errors: dict[str, str] = {}
        self._users: dict[str, int] = {}

    # ---- lookup -------------------------------------------------------------

    def spec(self, name: object) -> ModelSpec:
        if not isinstance(name, str) or name not in self.registry:
            known = ", ".join(self.registry)
            raise ServiceError("model_not_found", f"unknown model {name!r}; known: {known}")
        return self.registry[name]

    def path(self, name: str) -> Path:
        return self.models_dir / self.spec(name).name

    def _partial_dir(self, spec: ModelSpec) -> Path:
        return self.models_dir / f"{PARTIAL_PREFIX}{spec.name}"

    def is_downloaded(self, name: str) -> bool:
        spec = self.spec(name)
        final = self.models_dir / spec.name
        try:
            manifest = json.loads((final / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(manifest, dict) or manifest.get("revision") != spec.revision:
            return False
        return all(
            (final / f.path).is_file() and _file_size(final / f.path) == f.size for f in spec.files
        )

    def status(self, name: str) -> dict:
        spec = self.spec(name)
        with self._lock:
            job = self._jobs.get(spec.name)
            error = self._errors.get(spec.name)
        return {
            "name": spec.name,
            "size_mb": spec.size_mb,
            "downloaded": job is None and self.is_downloaded(spec.name),
            "downloading": job is not None,
            "progress": job.progress if job is not None else None,
            "error": None if job is not None else error,
        }

    def statuses(self) -> list[dict]:
        return [self.status(name) for name in self.registry]

    # ---- usage tracking (a model in use cannot be deleted) -----------------

    @contextmanager
    def in_use(self, name: str) -> Iterator[None]:
        spec = self.spec(name)
        with self._lock:
            self._users[spec.name] = self._users.get(spec.name, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                left = self._users.get(spec.name, 1) - 1
                if left > 0:
                    self._users[spec.name] = left
                else:
                    self._users.pop(spec.name, None)

    # ---- download -----------------------------------------------------------

    def start_download(self, name: str) -> tuple[bool, dict]:
        """Start a background download unless the model is already there.

        Returns ``(accepted, status)``: ``accepted`` is True when a download is
        now running (started now or earlier), False when nothing was needed.
        """
        spec = self.spec(name)
        if self.is_downloaded(spec.name):
            return False, self.status(spec.name)
        with self._lock:
            if spec.name not in self._jobs:
                self._start_locked(spec)
        return True, self.status(spec.name)

    def _start_locked(self, spec: ModelSpec) -> DownloadJob:
        job = DownloadJob(spec)
        self._jobs[spec.name] = job
        self._errors.pop(spec.name, None)
        thread = threading.Thread(
            target=self._run_job, args=(job,), name=f"download-{spec.name}", daemon=True
        )
        thread.start()
        return job

    def wait_ready(self, name: str, stop: threading.Event) -> Path:
        """Return the model dir, downloading the model first if needed.

        Joins a download that is already running. Raises ``download_failed``
        or ``Cancelled`` (when ``stop`` is set; the download itself goes on).
        """
        spec = self.spec(name)
        if self.is_downloaded(spec.name):
            return self.models_dir / spec.name
        with self._lock:
            job = self._jobs.get(spec.name) or self._start_locked(spec)
        while not job.finished.wait(0.25):
            if stop.is_set():
                raise Cancelled()
        if job.error:
            raise ServiceError("download_failed", job.error)
        if job.cancelled:
            raise ServiceError("download_failed", "the download was cancelled")
        if not self.is_downloaded(spec.name):
            raise ServiceError("download_failed", "model files are missing after the download")
        return self.models_dir / spec.name

    def _run_job(self, job: DownloadJob) -> None:
        name = job.spec.name
        started = time.monotonic()
        log.info("download %s: start (%d MB)", name, _mb(job.total_bytes))
        try:
            self._download(job)
            log.info("download %s: done in %.1f s", name, time.monotonic() - started)
        except Cancelled:
            job.cancelled = True
            log.info("download %s: cancelled", name)
        except ServiceError as exc:
            job.error = exc.message
            log.warning("download %s: failed: %s", name, exc.message)
        except Exception as exc:  # never let a download thread die silently
            job.error = f"unexpected error: {exc}"
            log.exception("download %s: unexpected error", name)
        finally:
            with self._lock:
                if self._jobs.get(name) is job:
                    del self._jobs[name]
                if job.error:
                    self._errors[name] = job.error
            job.finished.set()

    def _download(self, job: DownloadJob) -> None:
        spec = job.spec
        self.models_dir.mkdir(parents=True, exist_ok=True)
        partial = self._partial_dir(spec)
        marker = partial / REVISION_MARKER
        if partial.exists():
            try:
                same_revision = marker.read_text(encoding="utf-8").strip() == spec.revision
            except OSError:
                same_revision = False
            if not same_revision:
                _rmtree(partial)
        partial.mkdir(parents=True, exist_ok=True)
        marker.write_text(spec.revision, encoding="utf-8")

        for f in spec.files:
            if _file_size(partial / f.path) > f.size:
                (partial / f.path).unlink()
        job.done_bytes = sum(_file_size(partial / f.path) for f in spec.files)

        needed = spec.total_bytes - job.done_bytes
        free = shutil.disk_usage(self.models_dir).free
        if free < needed + DISK_MARGIN_BYTES:
            raise ServiceError(
                "download_failed",
                f"not enough disk space: need about {_mb(needed + DISK_MARGIN_BYTES)} MB, "
                f"{_mb(free)} MB free",
            )

        for f in spec.files:
            self._fetch_file(job, f, partial / f.path)

        manifest = {
            "name": spec.name,
            "repo": spec.repo,
            "revision": spec.revision,
            "files": [{"path": f.path, "size": f.size} for f in spec.files],
            "downloaded_at": int(time.time()),
        }
        (partial / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        final = self.models_dir / spec.name
        with self._lock:
            if job.cancel.is_set():
                raise Cancelled()
            if final.exists():
                old = self.models_dir / f"{OLD_PREFIX}{spec.name}-{uuid.uuid4().hex[:8]}"
                os.replace(final, old)
                shutil.rmtree(old, ignore_errors=True)
            os.replace(partial, final)

    def _fetch_file(self, job: DownloadJob, f: ModelFile, dest: Path) -> None:
        if _file_size(dest) == f.size:
            if self._digest_of(job, f, dest) == _expected_digest(f):
                return
            log.warning("download %s: %s is corrupt, fetching again", job.spec.name, f.path)
            job.done_bytes -= f.size
            dest.unlink()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._fetch_once(job, f, dest)
                return
            except _Retryable as exc:
                if attempt == MAX_ATTEMPTS:
                    raise ServiceError(
                        "download_failed", f"{f.path}: {exc} (after {attempt} attempts)"
                    ) from exc
                log.warning("download %s: %s: %s, retrying", job.spec.name, f.path, exc)
                if job.cancel.wait(self.retry_delay_s * attempt):
                    raise Cancelled() from exc

    def _digest_of(self, job: DownloadJob, f: ModelFile, path: Path) -> str:
        hasher = _new_hasher(f)
        with path.open("rb") as src:
            while chunk := src.read(CHUNK_BYTES):
                if job.cancel.is_set():
                    raise Cancelled()
                hasher.update(chunk)
        return hasher.hexdigest()

    def _url(self, spec: ModelSpec, f: ModelFile) -> str:
        return f"{self.endpoint}/{spec.repo}/resolve/{spec.revision}/{urllib.parse.quote(f.path)}"

    def _fetch_once(self, job: DownloadJob, f: ModelFile, dest: Path) -> None:
        have = _file_size(dest)
        hasher = _new_hasher(f)
        if have:
            with dest.open("rb") as src:
                while chunk := src.read(CHUNK_BYTES):
                    if job.cancel.is_set():
                        raise Cancelled()
                    hasher.update(chunk)

        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if have:
            headers["Range"] = f"bytes={have}-"
        request = urllib.request.Request(self._url(job.spec, f), headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout_s)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 429 or exc.code >= 500:
                raise _Retryable(f"HTTP {exc.code}") from exc
            raise ServiceError("download_failed", f"{f.path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise _Retryable(str(getattr(exc, "reason", exc))) from exc

        with response:
            status = response.status
            content_range = response.headers.get("Content-Range", "")
            if status == 206 and have and content_range.startswith(f"bytes {have}-"):
                mode = "ab"
            elif status == 200:
                mode = "wb"
                if have:  # the server ignored Range: start this file over
                    job.done_bytes -= have
                    have = 0
                    hasher = _new_hasher(f)
            elif status == 206:
                if have:
                    job.done_bytes -= have
                    dest.unlink()
                raise _Retryable(f"unexpected partial response ({content_range or 'no range'})")
            else:
                raise ServiceError("download_failed", f"{f.path}: HTTP {status}")

            try:
                with dest.open(mode) as out:
                    while True:
                        if job.cancel.is_set():
                            raise Cancelled()
                        # read1: return what has arrived (smooth progress, quick cancel)
                        chunk = response.read1(CHUNK_BYTES)
                        if not chunk:
                            break
                        out.write(chunk)
                        hasher.update(chunk)
                        have += len(chunk)
                        job.done_bytes += len(chunk)
                        if have > f.size:
                            break
            except OSError as exc:
                if exc.errno in DISK_ERRNOS:
                    raise ServiceError("download_failed", f"{f.path}: {exc}") from exc
                raise _Retryable(str(exc) or type(exc).__name__) from exc
            except http.client.HTTPException as exc:
                raise _Retryable(str(exc) or type(exc).__name__) from exc

        if have > f.size:
            job.done_bytes -= have
            dest.unlink()
            raise ServiceError("download_failed", f"{f.path}: server sent more data than expected")
        if have < f.size:
            raise _Retryable(f"connection closed at {have} of {f.size} bytes")
        if hasher.hexdigest() != _expected_digest(f):
            job.done_bytes -= have
            dest.unlink()
            raise ServiceError("download_failed", f"{f.path}: checksum mismatch")

    # ---- delete / cleanup ---------------------------------------------------

    def delete(self, name: str, on_remove: Callable[[str], object] | None = None) -> dict:
        """Remove a model (and any partial download). Idempotent.

        Raises ``busy`` while a transcription uses the model. A background
        download of the model is cancelled first.
        """
        spec = self.spec(name)
        with self._lock:
            if self._users.get(spec.name):
                raise ServiceError("busy", f"model {spec.name} is in use by a transcription")
            job = self._jobs.get(spec.name)
            if job is not None:
                job.cancel.set()
            self._errors.pop(spec.name, None)
        if job is not None:
            job.finished.wait(timeout=10)
        if on_remove is not None:
            on_remove(spec.name)
        with self._lock:
            if self._users.get(spec.name):
                raise ServiceError("busy", f"model {spec.name} is in use by a transcription")
            if spec.name not in self._jobs:  # a new download may have started meanwhile
                _rmtree(self._partial_dir(spec))
            _rmtree(self.models_dir / spec.name)
            self._errors.pop(spec.name, None)
        log.info("model %s: deleted", spec.name)
        return self.status(spec.name)

    def cleanup_stale(self) -> None:
        """Remove leftovers of interrupted replacements (keeps partials for resume)."""
        if not self.models_dir.is_dir():
            return
        for entry in self.models_dir.iterdir():
            if entry.name.startswith(OLD_PREFIX) and entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
