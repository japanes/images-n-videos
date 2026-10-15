"""One transcription at a time: download (if needed) → decode → load → transcribe."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import SAMPLE_RATE, Decoder, decode_audio
from .engine import WhisperEngine
from .errors import Cancelled, ServiceError
from .models import ModelStore

log = logging.getLogger("stt.service")

LANGUAGES = ("auto", "ru", "uk", "en")

# Fixed decoding options (same as the factory transcriber): silence is cut by
# the bundled Silero VAD before Whisper sees it, beam search of 5.
TRANSCRIBE_OPTIONS: dict[str, Any] = {"beam_size": 5, "vad_filter": True}


@dataclass(frozen=True)
class Job:
    path: Path
    model: str
    language: str  # one of LANGUAGES
    word_timestamps: bool


def _t(value: float) -> float:
    return round(float(value), 3)


def _word(w: Any) -> dict | None:
    text = (w.word or "").strip()
    if not text:
        return None
    return {
        "word": text,
        "start": _t(w.start),
        "end": _t(w.end),
        "probability": round(float(w.probability), 4),
    }


class SttService:
    def __init__(
        self, store: ModelStore, engine: WhisperEngine, decoder: Decoder = decode_audio
    ) -> None:
        self.store = store
        self.engine = engine
        self.decoder = decoder
        self._slot = threading.Lock()
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {"phase": None, "progress": None, "model": None, "duration": None, "started": None}

    @property
    def busy(self) -> bool:
        return self._slot.locked()

    def try_begin(self, model: str) -> bool:
        """Claim the single transcription slot. ``run`` must follow and frees it."""
        if not self._slot.acquire(blocking=False):
            return False
        with self._state_lock:
            self._state = {**self._idle_state(), "phase": "starting", "model": model}
            self._state["started"] = time.monotonic()
        return True

    def abort_begin(self) -> None:
        with self._state_lock:
            self._state = self._idle_state()
        self._slot.release()

    def _set(self, **changes: Any) -> None:
        with self._state_lock:
            self._state.update(changes)

    def progress(self) -> dict:
        with self._state_lock:
            state = dict(self._state)
        busy = self.busy and state["phase"] is not None
        progress = state["progress"]
        if busy and state["phase"] == "downloading":
            progress = self.store.status(state["model"])["progress"]
        return {
            "busy": busy,
            "phase": state["phase"] if busy else None,
            "progress": progress if busy else None,
            "model": state["model"] if busy else None,
            "duration": state["duration"] if busy else None,
            "elapsed_s": round(time.monotonic() - state["started"], 1) if busy else None,
        }

    def delete_model(self, name: str) -> dict:
        return self.store.delete(name, on_remove=self.engine.unload)

    def run(self, job: Job, stop: threading.Event) -> dict:
        """Do the work of a claimed slot (runs in a worker thread)."""
        started = time.monotonic()
        try:
            with self.store.in_use(job.model):
                if not self.store.is_downloaded(job.model):
                    self._set(phase="downloading", progress=0.0)
                model_dir = self.store.wait_ready(job.model, stop)

                self._set(phase="decoding", progress=0.0)
                audio = self.decoder(job.path, stop, lambda p: self._set(progress=round(p, 4)))
                duration = audio.shape[0] / SAMPLE_RATE
                self._set(phase="loading", progress=None, duration=_t(duration))
                if stop.is_set():
                    raise Cancelled()

                model = self.engine.acquire(job.model, model_dir)
                try:
                    self._set(phase="transcribing", progress=0.0)
                    result = self._transcribe(model, audio, duration, job, stop)
                finally:
                    self.engine.release()
            log.info(
                "transcribed %.1f s of audio with %s in %.1f s (%d segments)",
                duration,
                job.model,
                time.monotonic() - started,
                len(result["segments"]),
            )
            return result
        except Cancelled:
            log.info("transcription cancelled: the client went away")
            raise
        except ServiceError:
            raise
        except Exception as exc:
            log.exception("transcription failed")
            raise ServiceError("transcribe_failed", f"transcription failed: {exc}") from exc
        finally:
            with self._state_lock:
                self._state = self._idle_state()
            self._slot.release()

    def _transcribe(
        self, model: Any, audio: Any, duration: float, job: Job, stop: threading.Event
    ) -> dict:
        segments_iter, info = model.transcribe(
            audio,
            language=None if job.language == "auto" else job.language,
            word_timestamps=job.word_timestamps,
            **TRANSCRIBE_OPTIONS,
        )
        segments: list[dict] = []
        words: list[dict] = []
        texts: list[str] = []
        for seg in segments_iter:  # each step decodes up to 30 s of audio
            if stop.is_set():
                raise Cancelled()
            seg_words = [w for w in (_word(x) for x in (seg.words or [])) if w is not None]
            segments.append(
                {
                    "id": len(segments),
                    "start": _t(seg.start),
                    "end": _t(seg.end),
                    "text": seg.text.strip(),
                    "words": seg_words,
                }
            )
            words.extend(seg_words)
            texts.append(seg.text)
            if duration > 0:
                self._set(progress=round(min(1.0, seg.end / duration), 4))
        return {
            "task": "transcribe",
            "language": info.language,
            "duration": _t(info.duration),
            "text": "".join(texts).strip(),
            "segments": segments,
            "words": words,
            "model": job.model,
        }
