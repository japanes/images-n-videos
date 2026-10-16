"""The setting of a shoot, picked by hand or by the dice (free, no AI).

Eight axes — surface, backdrop, light, camera, air, props, palette, state of the
product — with a couple of hundred phrasings in ``data/shot_blocks.json``. Empty
means empty: the model then invents the world itself and nothing is said about a
setting. Filled means the English phrases go into the brief word for word,
followed by the rule that the setting is the author's decision.

The dice fill the four "always" axes and each "sometimes" axis with a 50 % chance,
and keep the picks compatible: an item whose ``avoid`` tags are already in the
frame is skipped, an item with ``requires`` needs one of those tags. A person
picking by hand may combine anything.

Ported from factory ``api/services/image/shot_scene.py``. Item names on screen
live in the locales (``ideas.scene.items.<id>``), so the browser gets ids only.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from vf.core.errors import AppError

BLOCKS_PATH = Path(__file__).resolve().parent / "data" / "shot_blocks.json"
MAX_ITEMS_PER_AXIS = 4
BLOCK_HEADING = "THE SETTING (chosen by the author)"


@lru_cache(maxsize=1)
def blocks() -> dict:
    return json.loads(BLOCKS_PATH.read_text(encoding="utf-8"))


def axes() -> list[dict]:
    return [a for a in blocks().get("axes") or [] if a.get("id")]


def axis_cap(axis: dict) -> int:
    try:
        cap = int(axis.get("max") or 1)
    except (TypeError, ValueError):
        cap = 1
    return max(1, min(cap, MAX_ITEMS_PER_AXIS))


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for axis in axes():
        for item in axis.get("items") or []:
            if item.get("id"):
                found[item["id"]] = {**item, "axis": axis["id"]}
    return found


def vocabulary() -> list[dict]:
    """What the picker draws: ``[{id, max, roll, items: [{id}]}]`` (names come from the locales)."""
    return [{"id": a["id"], "max": axis_cap(a), "roll": a.get("roll") or "always",
             "items": [{"id": i["id"]} for i in a.get("items") or [] if i.get("id")]} for a in axes()]


def _as_ids(scene: Any) -> list[str]:
    if not scene:
        return []
    if isinstance(scene, str):
        return [scene]
    if isinstance(scene, dict):
        return [x for value in scene.values() for x in _as_ids(value)]
    if isinstance(scene, Iterable):
        return [x for value in scene for x in _as_ids(value)]
    return []


def normalize(scene: Any) -> dict[str, list[str]]:
    """``{axis: [item ids]}`` in axis order, each axis cut to its cap. An unknown id is refused."""
    wanted = _as_ids(scene)
    if not wanted:
        return {}
    known = _index()
    seen: set[str] = set()
    picked: dict[str, list[str]] = {}
    for raw in wanted:
        block_id = str(raw).strip()
        if not block_id or block_id in seen:
            continue
        item = known.get(block_id)
        if item is None:
            raise AppError("ideas_scene_unknown", 400, "Unknown setting item", item=block_id)
        seen.add(block_id)
        picked.setdefault(item["axis"], []).append(block_id)
    out: dict[str, list[str]] = {}
    for axis in axes():
        chosen = picked.get(axis["id"]) or []
        if chosen:
            out[axis["id"]] = chosen[:axis_cap(axis)]
    return out


def _fits(item: dict, tags: set[str]) -> bool:
    if set(item.get("avoid") or []) & tags:
        return False
    needed = set(item.get("requires") or [])
    return not needed or bool(needed & tags)


def roll(seed: int | None = None) -> dict[str, list[str]]:
    """A whole setting at once, one item per axis that comes out."""
    rng = random.Random(seed)
    picked: dict[str, list[str]] = {}
    tags: set[str] = set()
    for axis in axes():
        if str(axis.get("roll") or "always") != "always" and rng.random() < 0.5:
            continue
        fitting = [i for i in axis.get("items") or [] if i.get("id") and _fits(i, tags)]
        if not fitting:
            continue
        chosen = rng.choice(fitting)
        picked[axis["id"]] = [chosen["id"]]
        tags |= set(chosen.get("tags") or [])
    return picked


def as_block(scene: Any) -> str:
    """The setting as English lines for the brief; "" when nothing is picked."""
    picked = normalize(scene)
    if not picked:
        return ""
    from vf.modules import library

    known = _index()
    lines = [BLOCK_HEADING]
    for axis in axes():
        phrases = [known[i]["en"] for i in picked.get(axis["id"]) or [] if i in known]
        if phrases:
            lines.append(f"{str(axis.get('name') or axis['id']).upper()}: {'; '.join(phrases)}")
    rule = library.render_layer("SHOT_SCENE_RULE", {}).strip()
    if rule:
        lines += ["", rule]
    return "\n".join(lines).strip()


__all__ = ["BLOCK_HEADING", "as_block", "axes", "axis_cap", "blocks", "normalize", "roll", "vocabulary"]
