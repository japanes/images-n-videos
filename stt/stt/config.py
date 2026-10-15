"""Service settings, read from the environment once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .registry import DEFAULT_REGISTRY, ModelSpec

DEFAULT_HF_ENDPOINT = "https://huggingface.co"
DEFAULT_IDLE_UNLOAD_S = 600


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def available_cpus() -> int:
    """CPUs this process may run on (respects affinity / cpusets)."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    version: str = "0.0.0-dev"
    # 0 = use every CPU available to the container.
    cpu_threads: int = 0
    # Free the loaded model after this many idle seconds (0 = keep it loaded).
    idle_unload_s: int = DEFAULT_IDLE_UNLOAD_S
    hf_endpoint: str = DEFAULT_HF_ENDPOINT
    registry: dict[str, ModelSpec] = field(default_factory=lambda: dict(DEFAULT_REGISTRY))

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def effective_cpu_threads(self) -> int:
        return self.cpu_threads or available_cpus()

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = os.environ.get("VF_DATA_DIR", "").strip() or "/data"
        return cls(
            data_dir=Path(data_dir),
            version=os.environ.get("VF_VERSION", "").strip() or "0.0.0-dev",
            cpu_threads=_int_env("STT_CPU_THREADS", 0),
            idle_unload_s=_int_env("STT_IDLE_UNLOAD_S", DEFAULT_IDLE_UNLOAD_S),
            hf_endpoint=(os.environ.get("HF_ENDPOINT", "").strip() or DEFAULT_HF_ENDPOINT).rstrip(
                "/"
            ),
        )
