"""Decode the audio track of any audio or video file to 16 kHz mono float32.

Uses PyAV, whose wheels bundle the FFmpeg libraries, so the image needs no
ffmpeg binary. The approach follows ``faster_whisper.audio.decode_audio``
(skip broken frames, batch frames, resample to s16 mono) and adds progress,
cancellation, a local-files-only protocol whitelist and clear error codes.
"""

from __future__ import annotations

import gc
import io
import threading
from collections.abc import Callable
from pathlib import Path

import av
import numpy as np

from .errors import Cancelled, ServiceError

SAMPLE_RATE = 16000
# Resample in batches of this many input samples (as faster-whisper does).
BATCH_SAMPLES = 500_000

Decoder = Callable[..., np.ndarray]


def _media_seconds(container, stream) -> float | None:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / av.time_base
    return None


def decode_audio(
    path: Path,
    stop: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> np.ndarray:
    try:
        container = av.open(
            str(path),
            mode="r",
            metadata_errors="ignore",
            # Only plain local files: playlists cannot pull anything from the network.
            container_options={"protocol_whitelist": "file"},
        )
    except av.FFmpegError as exc:
        raise ServiceError("transcribe_failed", f"cannot read the media file: {exc}") from exc

    raw = io.BytesIO()
    try:
        with container:
            if not container.streams.audio:
                raise ServiceError("no_audio", "the file has no audio track")
            stream = container.streams.audio[0]
            total = _media_seconds(container, stream)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            fifo = av.AudioFifo()

            def flush(frame) -> None:
                for out in resampler.resample(frame):
                    raw.write(out.to_ndarray().tobytes())

            frames = container.decode(stream)
            while True:
                if stop is not None and stop.is_set():
                    raise Cancelled()
                try:
                    frame = next(frames)
                except StopIteration:
                    break
                except av.InvalidDataError:
                    continue  # skip a broken packet, like faster-whisper does
                if on_progress is not None and total and frame.time is not None:
                    on_progress(min(1.0, max(0.0, frame.time / total)))
                frame.pts = None  # the fifo would otherwise reject timestamp gaps
                fifo.write(frame)
                if fifo.samples >= BATCH_SAMPLES:
                    flush(fifo.read())
            if fifo.samples > 0:
                flush(fifo.read())
            flush(None)  # drain the resampler
            resampler = fifo = None  # drop references before gc.collect()
    except (ServiceError, Cancelled):
        raise
    except (av.FFmpegError, ValueError) as exc:
        raise ServiceError("transcribe_failed", f"cannot decode the audio: {exc}") from exc
    finally:
        # PyAV resampler objects are only freed by the cycle collector
        # (https://github.com/SYSTRAN/faster-whisper/issues/390).
        gc.collect()

    audio = np.frombuffer(raw.getbuffer(), dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        raise ServiceError("no_audio", "the audio track is empty")
    if on_progress is not None:
        on_progress(1.0)
    return audio
