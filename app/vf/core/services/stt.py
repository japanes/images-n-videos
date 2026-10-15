"""Client of the ``stt`` container (faster-whisper, runs locally, free)."""

from __future__ import annotations

from vf.core.config import get_config
from vf.core.services._http import call


def _url(path: str) -> str:
    return get_config().stt_url + path


async def health() -> dict:
    return await call("stt", "GET", _url("/health"), timeout=5)


async def models() -> list[dict]:
    return await call("stt", "GET", _url("/models"), timeout=10)


async def download(name: str) -> dict:
    return await call("stt", "POST", _url("/models/download"), json={"name": name}, timeout=30)


async def remove(name: str) -> None:
    await call("stt", "DELETE", _url(f"/models/{name}"), timeout=30)


async def progress() -> dict:
    return await call("stt", "GET", _url("/progress"), timeout=5)


async def transcribe(rel: str, *, model: str, language: str = "auto", word_timestamps: bool = True) -> dict:
    """Whisper ``verbose_json``: {text, language, duration, segments[], words[]}.
    The first call may download the model, so the timeout is long."""
    body = {"input": rel, "model": model, "language": language, "word_timestamps": word_timestamps}
    return await call("stt", "POST", _url("/transcribe"), json=body, timeout=60 * 60)
