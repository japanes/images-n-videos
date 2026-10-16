"""Toggle "Improve prompt": a text model rewrites a short request into a fuller prompt.

The model comes from the role ``prompt_enhance`` (Settings → Models), the text
from the versioned prompt file ``chat.enhance``. Every call goes through the
Google gateway, so it is in the spend journal with refs to the chat and the
request message. The person sees the improved text in the message and can
send their own words instead.
"""

from __future__ import annotations

from vf.core import models_registry, pricing, prompts
from vf.core.errors import AppError

PROMPT = "chat.enhance"
PURPOSE = "prompt_enhance"
ROLE = "prompt_enhance"
PHOTO_SIDE = 1024
MAX_CHARS = {"image": 1500, "video": 1200}
ROLE_LINES = {
    "reference": "reference photo (what the subject or the look should be)",
    "subject": "photo of a subject that must appear",
    "base": "the picture to be changed",
    "first": "first frame of the video",
    "last": "last frame of the video",
}


def model() -> dict:
    return models_registry.model_for_role(ROLE)


def price(n_images: int = 0) -> tuple[float, str]:
    m = model()
    return pricing.estimate_text(m, purpose=PURPOSE, input_images=n_images), m["id"]


def _image(file_id: int):
    from vf.modules.video import runs as video_runs

    return video_runs.image_blob(file_id, max_side=PHOTO_SIDE)


def _attachment_lines(attachments: list[dict]) -> str:
    if not attachments:
        return "none"
    return "\n".join(f"{i}. {ROLE_LINES.get(a.get('role'), a.get('role') or 'photo')}"
                     for i, a in enumerate(attachments, 1))


async def improve(*, mode: str, text: str, attachments: list[dict], refs: list[tuple[str, int]]) -> dict:
    """The improved text with what the call cost. Raises the gateway's error on failure."""
    images = []
    for a in attachments:
        try:
            images.append(_image(int(a["file_id"])))
        except Exception:  # noqa: BLE001 — a file that cannot be read is left out, the line stays
            continue
    pf = prompts.get(PROMPT)
    result = await prompts.run_prompt(
        PROMPT, {"mode": mode, "attachments": _attachment_lines(attachments), "text": text,
                 "max_chars": MAX_CHARS.get(mode, 1500)},
        purpose=PURPOSE, images=images, refs=refs)
    improved = (result.text or "").strip().strip('"').strip()
    if not improved:
        raise AppError("chat_enhance_empty", 502, "The model answered without a text")
    return {"text": improved[:4000], "model_id": result.model_id, "cost_usd": round(result.cost_usd or 0, 6),
            "call_ids": list(result.call_ids or []), "prompt_code": pf.code, "prompt_version": pf.version}


__all__ = ["MAX_CHARS", "PROMPT", "PURPOSE", "improve", "model", "price"]
