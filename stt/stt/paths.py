"""Validation of the ``input`` path a client sends."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .errors import ServiceError

# Top-level folders of the shared data volume that are never valid inputs.
DENIED_TOP_DIRS = frozenset({"secrets", "models"})


def resolve_input(data_dir: Path, raw: object) -> Path:
    """Turn a client path (relative to the data dir) into a safe absolute path.

    Rules: relative, no ``..``, the real path (after symlinks) stays inside the
    data dir and outside ``secrets/`` and ``models/``, and it is an existing file.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ServiceError("bad_request", "input must be a non-empty path")
    if "\x00" in raw:
        raise ServiceError("bad_request", "input contains a NUL byte")
    if raw.startswith(("/", "\\")) or (len(raw) > 1 and raw[1] == ":"):
        raise ServiceError("bad_request", "input must be relative to the data dir")

    rel = PurePosixPath(raw)
    if ".." in rel.parts:
        raise ServiceError("bad_request", "input must not contain '..'")

    root = Path(os.path.realpath(data_dir))
    real = Path(os.path.realpath(root / rel))
    if real != root and root not in real.parents:
        raise ServiceError("bad_request", "input points outside the data dir")

    inside = real.relative_to(root).parts
    if inside and inside[0] in DENIED_TOP_DIRS:
        raise ServiceError("bad_request", f"input must not point into {inside[0]}/")

    if not real.is_file():
        raise ServiceError("not_found", f"file not found: {raw}")
    return real
