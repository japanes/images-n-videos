"""The view of one chat sent to the browser: the list fields plus its settings,
the draft of the composer and what the settings panel needs to draw itself."""

from __future__ import annotations

from typing import Any

from vf.core import settings
from vf.core.errors import AppError
from vf.modules.chat import enhance, messages, send, store
from vf.modules.studio import blocks as studio_blocks
from vf.modules.studio import compose
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_EDIT
from vf.modules.video import extend as video_extend


def image_blocks(chat: dict) -> dict:
    """Prompt blocks of a new picture request with the chat's settings (switches of the panel)."""
    try:
        work, frame = send.synthetic(store.image_settings(chat), chat.get("kit_id"))
        eff = W.effective(work, frame)
        return {"items": studio_blocks.catalog(eff["blocks"], compose.facts(work, frame, eff)), "error": None}
    except AppError as exc:
        return {"items": [], "error": exc.code}


def _enhance_info() -> dict:
    try:
        usd, model_id = enhance.price(0)
    except AppError as exc:
        return {"model_id": None, "usd": None, "error": exc.code}
    return {"model_id": model_id, "usd": round(usd, 6), "error": None}


def limits() -> dict:
    return {"max_attachments": int(settings.get("general.max_attachments", 10) or 10),
            "max_text": send.MAX_TEXT, "max_edit": MAX_EDIT, "max_extend": video_extend.MAX_TEXT,
            "max_draft": store.MAX_DRAFT, "image_roles": list(store.IMAGE_ROLES),
            "video_roles": list(store.VIDEO_ROLES)}


def chat_public(chat: dict) -> dict:
    d = store.draft(chat)
    out: dict[str, Any] = store.list_item(chat)
    out.update({
        "title_auto": bool(chat.get("title_auto")), "kit_id": chat.get("kit_id"),
        "archived_at": chat.get("archived_at"), "meta": chat.get("meta_json") or {},
        "image_settings": store.image_settings(chat), "video_settings": store.video_settings(chat),
        "draft": {**d, "attachments": [{**a, "file": messages._file(a.get("file_id"))}
                                       for a in d.get("attachments") or []],
                  "reply": messages.reply_brief(d.get("reply_to"), d.get("reply_index") or 0)},
        "image_blocks": image_blocks(chat), "enhance": _enhance_info(), "limits": limits(),
    })
    return out


def get_chat(chat_id: int) -> dict:
    return chat_public(store.chat_row(chat_id))


__all__ = ["chat_public", "get_chat", "image_blocks", "limits"]
