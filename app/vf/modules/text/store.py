"""Rows of the text module and the things around a design (its frame, work, kit)."""

from __future__ import annotations

from typing import Any

from vf.core import db
from vf.core.errors import NotFound
from vf.modules.studio import works as W
from vf.modules.text import common as C


def design_row(design_id: int) -> dict:
    row = db.get("text_designs", int(design_id))
    if row is None:
        raise NotFound("text_design", id=design_id)
    return row


def frame_of(design: dict) -> dict:
    return W.frame_row(design["frame_id"])


def work_of(frame: dict) -> dict:
    return W.work_row(frame["work_id"])


def snapshot_for(design: dict, work: dict) -> dict | None:
    """The work's brand snapshot, when the design shows the work's own kit."""
    snap = work.get("brand_json") or None
    if not snap:
        return None
    if design.get("kit_id") in (None, snap.get("kit_id")):
        return snap
    return None


def refs_of(design: dict, extra: tuple[tuple[str, int], ...] = ()) -> list[tuple[str, int]]:
    """Journal refs of every paid call made for a design: the design, its frame and the chat."""
    out = [(C.REF_DESIGN, design["id"]), (W.REF_FRAME, design["frame_id"])]
    if design.get("chat_id"):
        out.append(("chat", design["chat_id"]))
    if design.get("message_id"):
        out.append(("chat_message", design["message_id"]))
    out.extend(extra)
    return out


def add_cost(design_id: int, usd: Any) -> None:
    try:
        value = float(usd or 0)
    except (TypeError, ValueError):
        return
    if value > 0:
        db.execute("UPDATE text_designs SET cost_usd = cost_usd + ?, updated_at = ? WHERE id = ?",
                   (value, db.now(), design_id))


def update(design_id: int, values: dict) -> None:
    db.update("text_designs", design_id, {**values, "updated_at": db.now()})


def int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


__all__ = ["add_cost", "design_row", "frame_of", "int_or_none", "refs_of", "snapshot_for", "update", "work_of"]
