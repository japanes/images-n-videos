"""Describe a subject from its photos (paid: one Gemini call, role ``vision_describe``).

Ported from factory ``api/services/subject_describe.py``:
  * up to 3 photos, in the user's order, scaled to fit 1024 px (JPEG q80);
  * the answer is JSON ``{description, name}``, description at most 1200 chars;
  * a hand-written description is never replaced silently: without ``force``
    the call stops with ``subject_description_manual`` (409) and the UI asks;
  * when FOCUS is given and the current text came from the photos, the old text
    is not passed as notes (it may describe the wrong thing).
The user's name is never overwritten: the suggested name is used only when the
subject has no name yet.
"""

from __future__ import annotations

import asyncio
import io

from vf.core import files, prompts
from vf.core.errors import AppError
from vf.core.google import Blob
from vf.modules.brand.common import clean_text, publish
from vf.modules.brand.subjects import MAX_FOCUS, _photos, _row, _touch, get_subject

PROMPT_CODE = "SUBJECT_DESCRIBE"
PURPOSE = "subject_describe"
MAX_PHOTOS = 3
THUMB_SIDE = 1024
MAX_DESCRIPTION_CHARS = 1200
MAX_NAME_CHARS = 60
UNNAMED = "(unnamed)"
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 700


def _shrink(data: bytes, mime: str) -> tuple[bytes, str]:
    """Fit inside 1024x1024, JPEG q80. A picture that cannot be read goes as is."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                background = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                im = background
            im.thumbnail((THUMB_SIDE, THUMB_SIDE))
            out = io.BytesIO()
            im.convert("RGB").save(out, "JPEG", quality=80)
            return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return data, mime


def _clean_description(text: str) -> str:
    return " ".join(str(text or "").split())[:MAX_DESCRIPTION_CHARS]


def _clean_name(text: str) -> str:
    return " ".join(str(text or "").split()).strip(" .:;-—")[:MAX_NAME_CHARS]


def _blobs(photo_rows: list[dict]) -> list[Blob]:
    out = []
    for photo in photo_rows[:MAX_PHOTOS]:
        try:
            row = files.get(photo["file_id"])
            data, mime = _shrink(files.read_bytes(photo["file_id"]), row["mime"])
        except (AppError, OSError):
            continue
        out.append(Blob(data, mime, photo["file_id"]))
    return out


async def describe_subject(subject_id: int, *, force: bool = False, focus: str | None = None) -> dict:
    """Run the prompt and save the answer. Returns
    ``{"subject": ..., "description", "name", "photos_used", "cost_usd", "call_ids"}``."""
    row = _row(subject_id)
    if row["description"].strip() and row["description_source"] == "manual" and not force:
        raise AppError("subject_description_manual", 409,
                       "The description was written by hand; confirm to replace it")
    photo_rows = _photos(subject_id)
    if not photo_rows:
        raise AppError("subject_no_photos", 400, "Add at least one photo first")

    focus_text = clean_text(row["describe_focus"] if focus is None else focus, MAX_FOCUS)
    existing = row["description"].strip()
    if focus_text and row["description_source"] == "photo":
        existing = ""  # the old AI text may describe a different thing

    blobs = await asyncio.to_thread(_blobs, photo_rows)
    if not blobs:
        raise AppError("subject_no_photos", 400, "The photos could not be read")

    result = await prompts.run_prompt(
        PROMPT_CODE,
        {"name": row["name"] or UNNAMED, "kind": row["kind"], "photo_count": len(blobs),
         "focus": focus_text, "existing": existing},
        purpose=PURPOSE, images=blobs, refs=[("subject", subject_id)],
        temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    answer = result.json if isinstance(result.json, dict) else {}
    description = _clean_description(answer.get("description", ""))
    name = _clean_name(answer.get("name", ""))
    if not description:
        raise AppError("subject_describe_empty", 502, "The model returned no description",
                       call_ids=result.call_ids)

    values = {"description": description, "description_source": "photo", "describe_focus": focus_text}
    if not row["name"].strip() and name and name != UNNAMED:
        values["name"] = name
    _touch(subject_id, values)
    publish("subject", subject_id=subject_id)
    return {"subject": get_subject(subject_id), "description": description, "name": name,
            "photos_used": len(blobs), "cost_usd": result.cost_usd, "call_ids": result.call_ids,
            "model_id": result.model_id}
