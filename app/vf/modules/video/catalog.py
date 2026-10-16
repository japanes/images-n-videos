"""What the video module offers: camera moves, the video models and their limits,
module settings. Data, not decisions: every model and limit comes from the registry."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from vf.core import models_registry, settings
from vf.core.errors import AppError

DATA = Path(__file__).resolve().parent / "data"

# Files the extension model can take, unless the model's caps say otherwise.
MAX_INPUT_VIDEO_MB = 20
INPUT_VIDEO_MIMES = ("video/mp4", "video/quicktime", "video/webm")

# Gemini image models draw a storyboard sheet in one of these shapes.
SHEET_ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")

LANGUAGE_NAMES = {"ru": "Russian", "uk": "Ukrainian", "en": "English"}

settings.define("video.extend_tail_seconds", 10, group="video", kind="int", min=2, max=30,
                label_key="video.settings.tailSeconds.label", help_key="video.settings.tailSeconds.help")
settings.define("video.extend_align", True, group="video", kind="bool",
                label_key="video.settings.align.label", help_key="video.settings.align.help")
settings.define("video.extend_crossfade_seconds", 0.2, group="video", kind="float", min=0.0, max=2.0,
                label_key="video.settings.crossfade.label", help_key="video.settings.crossfade.help")
settings.define("video.research_cache_days", 14, group="video", kind="int", min=0, max=365,
                label_key="video.settings.researchDays.label", help_key="video.settings.researchDays.help")


# ── camera moves ────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _moves_file() -> dict:
    return json.loads((DATA / "camera_moves.json").read_text(encoding="utf-8"))


def camera_moves() -> list[dict]:
    """``[{code, category}]`` in catalogue order (labels live in the web locales)."""
    return [{"code": m["code"], "category": m["category"]} for m in _moves_file()["moves"]]


def camera_categories() -> list[str]:
    return list(_moves_file()["categories"])


def camera_move(code: str) -> dict | None:
    for move in _moves_file()["moves"]:
        if move["code"] == code:
            return move
    return None


def clip_phrase(code: str | None) -> str:
    """The words a clip prompt gets for a move; '' when no move is chosen."""
    move = camera_move(code) if code else None
    return (move or {}).get("clip_phrase") or ""


def check_camera_move(code: str | None) -> str:
    code = (code or "").strip()
    if code and camera_move(code) is None:
        raise AppError("video_camera_unknown", 400, camera_move=code)
    return code


# ── models ─────────────────────────────────────────────────────────────────


def video_models(*, enabled_only: bool = True) -> list[dict]:
    return models_registry.list_models("video", enabled_only=enabled_only)


def model(model_id: str | None) -> dict:
    """The video model asked for (checked), or the default one."""
    return models_registry.resolve("video", model_id or None)


def caps(m: dict) -> dict:
    return m.get("caps") or {}


def max_input_seconds(m: dict) -> float:
    try:
        return float(caps(m).get("max_input_video_seconds") or 0)
    except (TypeError, ValueError):
        return 0.0


def extension_models() -> list[dict]:
    """Video models that can continue a video (they take a video as input)."""
    return [m for m in video_models() if max_input_seconds(m) > 0]


def extension_model(model_id: str | None) -> dict:
    if model_id:
        m = model(model_id)
        if max_input_seconds(m) <= 0:
            raise AppError("video_extend_unsupported", 400, model_id=m["id"])
        return m
    found = extension_models()
    if not found:
        raise AppError("video_extend_unsupported", 409, model_id=None)
    return found[0]


def resolutions(m: dict) -> dict[str, list[int]]:
    return models_registry.video_resolutions(m)


def durations(m: dict, resolution: str | None = None) -> list[int]:
    table = resolutions(m)
    if resolution and resolution.lower() in table:
        return list(table[resolution.lower()])
    return sorted({d for ds in table.values() for d in ds})


def aspects(m: dict) -> list[str]:
    return list(caps(m).get("allowed_aspects") or ["9:16", "16:9"])


def snap_duration(value: float | int | None, allowed: list[int]) -> int | None:
    """The allowed length closest to ``value`` (a tie goes to the longer one)."""
    if not allowed:
        return None
    if value is None:
        return allowed[0]
    return min(allowed, key=lambda d: (abs(d - float(value)), -d))


def snap_resolution(value: str | None, m: dict) -> str:
    table = resolutions(m)
    names = list(table)
    if value and value.lower() in table:
        return value.lower()
    return names[0] if names else "720p"


def fit_settings(m: dict, *, seconds: float | None, resolution: str | None, aspect: str | None) -> dict:
    """Bring duration, resolution and shape inside what the model allows."""
    res = snap_resolution(resolution, m)
    allowed = durations(m, res)
    shapes = aspects(m)
    return {
        "resolution": res,
        "duration": snap_duration(seconds, allowed),
        "aspect": aspect if aspect in shapes else shapes[0],
    }


def resolution_rank(name: str) -> int:
    digits = "".join(ch for ch in str(name) if ch.isdigit())
    value = int(digits or 0)
    return value * 1000 if str(name).lower().endswith("k") else value


def resolution_of_size(width: int | None, height: int | None) -> str:
    """The class of a picture by its shorter side: 4k / 1080p / 720p."""
    short = min(int(width or 0), int(height or 0)) or max(int(width or 0), int(height or 0))
    if short >= 2000:
        return "4k"
    if short >= 1000:
        return "1080p"
    return "720p"


def input_video_limits(m: dict) -> dict:
    c = caps(m)
    mb = c.get("max_input_video_mb") or MAX_INPUT_VIDEO_MB
    mimes = c.get("input_video_mimes") or list(INPUT_VIDEO_MIMES)
    return {"max_mb": float(mb), "mimes": list(mimes), "max_seconds": max_input_seconds(m)}


def max_references(m: dict) -> int:
    return int(caps(m).get("max_asset_references") or 0)


def model_info(m: dict) -> dict:
    """What the settings form needs to know about one video model."""
    c = caps(m)
    return {
        "id": m["id"], "title": m["title"], "api": m["api"], "is_default": m["is_default"],
        "available": m["available"], "preview": m.get("preview", False),
        "resolutions": resolutions(m), "durations": durations(m), "aspects": aspects(m),
        "first_frame": bool(c.get("supports_first_frame", True)),
        "last_frame": bool(c.get("supports_last_frame")),
        "max_references": max_references(m),
        "frame_shadows_references": bool(c.get("frame_shadows_references")),
        "sound_switch": bool(c.get("supports_audio_switch")),
        "negative_prompt": bool(c.get("supports_negative_prompt")),
        "extends": max_input_seconds(m) > 0,
        "input_video": input_video_limits(m) if max_input_seconds(m) > 0 else None,
    }


# ── storyboard sheet shape ──────────────────────────────────────────────────


def _ratio(aspect: str) -> float:
    try:
        w, h = (float(x) for x in str(aspect).split(":"))
        return w / h if h else 1.0
    except ValueError:
        return 1.0


def nearest_aspect(target: float, choices: list[str] | tuple[str, ...]) -> str:
    return min(choices, key=lambda a: abs(math.log(_ratio(a)) - math.log(target)))


def storyboard_grid(panels: int, aspect: str) -> tuple[int, int]:
    """Columns and rows for ``panels`` frames of shape ``aspect``: few empty cells,
    a sheet close to a square."""
    ratio = _ratio(aspect)
    best: tuple[float, int, int] | None = None
    for cols in range(1, panels + 1):
        rows = math.ceil(panels / cols)
        score = (cols * rows - panels) * 0.5 + abs(math.log(cols * ratio / rows))
        if best is None or score < best[0]:
            best = (score, cols, rows)
    assert best is not None
    return best[1], best[2]


def sheet_aspect(cols: int, rows: int, aspect: str, allowed: list[str] | None = None) -> str:
    return nearest_aspect(cols * _ratio(aspect) / rows, allowed or list(SHEET_ASPECTS))


def language() -> tuple[str, str]:
    code = str(settings.get("general.text_language") or "en")
    return code, LANGUAGE_NAMES.get(code, "English")
