"""Keeps at most one Whisper model in memory.

Loading large-v3-turbo takes seconds and ~1.5 GB of RAM, so the model stays
loaded between requests and is freed after ``idle_unload_s`` without use.
Switching to another model drops the old one first so two never coexist.
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("stt.engine")

ModelFactory = Callable[[Path, int], Any]


def load_faster_whisper(model_dir: Path, cpu_threads: int) -> Any:
    # Imported lazily: it pulls in ctranslate2/onnxruntime, which tests can skip.
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
        num_workers=1,
        local_files_only=True,
    )


class WhisperEngine:
    def __init__(
        self,
        cpu_threads: int,
        idle_unload_s: int,
        factory: ModelFactory | None = None,
        *,
        check_interval_s: float = 30.0,
    ) -> None:
        self.cpu_threads = cpu_threads
        self.idle_unload_s = idle_unload_s
        self._factory = factory or load_faster_whisper
        self._lock = threading.Lock()
        self._model: Any = None
        self._name: str | None = None
        self._dir: Path | None = None
        self._in_use = 0
        self._last_used = time.monotonic()
        self._closed = threading.Event()
        self._check_interval_s = check_interval_s
        if idle_unload_s > 0:
            threading.Thread(target=self._idle_loop, name="idle-unload", daemon=True).start()

    @property
    def loaded_name(self) -> str | None:
        with self._lock:
            return self._name

    def acquire(self, name: str, model_dir: Path) -> Any:
        """Return the loaded model ``name``, loading it if needed. Pair with ``release``."""
        with self._lock:
            if self._model is not None and self._name == name and self._dir == model_dir:
                self._in_use += 1
                return self._model
            if self._in_use:
                raise RuntimeError("another model is in use")
            self._drop_locked()
            # Mark as in use while loading so the idle thread leaves it alone.
            self._in_use += 1
        try:
            started = time.monotonic()
            model = self._factory(model_dir, self.cpu_threads)
            log.info(
                "model %s: loaded in %.1f s (%d threads)",
                name,
                time.monotonic() - started,
                self.cpu_threads,
            )
        except BaseException:
            with self._lock:
                self._in_use -= 1
            raise
        with self._lock:
            self._model, self._name, self._dir = model, name, model_dir
            return model

    def release(self) -> None:
        with self._lock:
            self._in_use = max(0, self._in_use - 1)
            self._last_used = time.monotonic()

    def unload(self, name: str | None = None) -> bool:
        """Free the model (only ``name`` if given). Returns True if something was freed."""
        with self._lock:
            if self._model is None or self._in_use:
                return False
            if name is not None and name != self._name:
                return False
            self._drop_locked()
            return True

    def close(self) -> None:
        self._closed.set()

    def _drop_locked(self) -> None:
        if self._model is None:
            return
        log.info("model %s: unloaded", self._name)
        self._model = None
        self._name = None
        self._dir = None
        gc.collect()

    def _idle_loop(self) -> None:
        interval = min(self._check_interval_s, float(self.idle_unload_s))
        while not self._closed.wait(interval):
            with self._lock:
                idle_for = time.monotonic() - self._last_used
                if self._model is not None and not self._in_use and idle_for >= self.idle_unload_s:
                    self._drop_locked()
