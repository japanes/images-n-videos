"""The built-in shot pack: 36 shots in categories (``avatar-shots.json`` next to this file).

The pack is data, not code: the English ``prompt`` of a shot goes to the model,
the titles shown in the app come from the locales (``avatars.shots.SHOT_xx``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from vf.core.errors import AppError

PATH = Path(__file__).with_name("avatar-shots.json")


@lru_cache(maxsize=1)
def _data() -> dict:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    shots = sorted(data.get("shots") or [], key=lambda s: (int(s.get("sort") or 0), s["code"]))
    return {"categories": data.get("categories") or [], "shots": shots}


def shots() -> list[dict]:
    """``[{code, title, category, sort, description, prompt}]`` in pack order."""
    return [dict(s) for s in _data()["shots"]]


def codes() -> list[str]:
    return [s["code"] for s in _data()["shots"]]


def shot(code: str) -> dict:
    for s in _data()["shots"]:
        if s["code"] == code:
            return dict(s)
    raise AppError("avatar_shot_unknown", 400, "Unknown shot", code=code)


def categories() -> list[dict]:
    return [dict(c) for c in _data()["categories"]]


def public() -> dict:
    """What the browser gets: the categories and the shots (with their English prompts,
    so «What is sent» can be shown before a shot is drawn)."""
    return {"categories": categories(), "shots": shots(), "count": len(_data()["shots"])}
