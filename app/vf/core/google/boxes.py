"""Object frames from Gemini answers, as fractions of the picture.

Gemini returns frames as ``box_2d = [ymin, xmin, ymax, xmax]`` on a 0..1000
grid (y first). The app keeps frames as ``{"x", "y", "w", "h"}`` fractions
0..1 of the picture, top-left origin. Ported from factory
``api/services/image/segment.py`` (``_box_from``), plus clamping to the picture.
"""

from __future__ import annotations

import math
from typing import Any

GRID = 1000.0


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def box_2d_to_fractions(raw: Any, scale: float = GRID) -> dict[str, float] | None:
    """``[ymin, xmin, ymax, xmax]`` (or ``{"x", "y", "w"|"width", "h"|"height"}``)
    on a ``scale`` grid -> ``{"x", "y", "w", "h"}`` in 0..1. ``None`` when empty."""
    if isinstance(raw, dict):
        x, y = _num(raw.get("x")) / scale, _num(raw.get("y")) / scale
        w = _num(raw.get("w") if raw.get("w") is not None else raw.get("width")) / scale
        h = _num(raw.get("h") if raw.get("h") is not None else raw.get("height")) / scale
        x0, y0, x1, y1 = x, y, x + w, y + h
        if w <= 0 or h <= 0:
            return None
    elif isinstance(raw, list | tuple) and len(raw) >= 4:
        ymin, xmin, ymax, xmax = (_num(v) / scale for v in raw[:4])
        x0, x1 = min(xmin, xmax), max(xmin, xmax)
        y0, y1 = min(ymin, ymax), max(ymin, ymax)
    else:
        return None
    x0, y0, x1, y1 = _clamp(x0), _clamp(y0), _clamp(x1), _clamp(y1)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return {"x": round(x0, 6), "y": round(y0, 6), "w": round(x1 - x0, 6), "h": round(y1 - y0, 6)}
