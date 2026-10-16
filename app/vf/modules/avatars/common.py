"""Constants and small helpers shared by the avatar files."""

from __future__ import annotations

import logging
import re
from typing import Any

from vf.core import events

log = logging.getLogger("vf.avatars")

# Journal refs, media-library usage type and the files' source types.
REF_AVATAR = "avatar"
REF_PHOTO = "avatar_photo"
REF_MESSAGE = "chat_message"        # every paid call also carries the chat message that shows it
USAGE_TYPE = "avatar"
SOURCE_PHOTO = "avatar_photo"       # photos the person uploaded (sources, own pictures in a slot)
SOURCE_IMAGE = "avatar_image"       # pictures drawn by the image model (candidates, shots)

# Purposes in the spend journal.
PURPOSE_IDENTITY = "avatar_identity"
PURPOSE_MASTER = "avatar_master"
PURPOSE_SHOT = "avatar_shot"
PURPOSE_FIX = "avatar_fix"

# Background jobs.
JOB_PHOTO = "avatar.photo"          # one picture: a face candidate, a shot, or a fix of a shot
JOB_DESCRIBE = "avatar.describe"    # «Describe»: the master identity

# Prompt files (app/prompts/avatars/…) and the model role of «Describe».
PROMPT_IDENTITY = "avatars.identity"
PROMPT_MASTER = "avatars.master"
PROMPT_SHOT = "avatars.shot"
PROMPT_FIX = "avatars.fix"
ROLE_DESCRIBE = "vision_describe"

# Chat message kinds (web/components/chat/kinds/Avatar*.vue).
KIND_CARD = "avatar.card"
KIND_IDENTITY = "avatar.identity"
KIND_CANDIDATES = "avatar.candidates"
KIND_PACK = "avatar.pack"

MODES = ("reference", "description", "auto")
PHOTO_KINDS = ("source", "candidate", "face", "shot")
BUSY = ("queued", "drawing")

MAX_NAME = 120
MAX_BRIEF = 2000
MAX_IDENTITY = 6000
MIN_IDENTITY = 200
MAX_ANGLE = 60
MAX_TITLE = 120
MAX_CUSTOM_PROMPT = 4000
MAX_FIX = 2000
MAX_SOURCE_PHOTOS = 12
IDENTITY_PHOTOS = 3      # sent to «Describe», 1024 px JPEG
SUBJECT_PHOTOS = 4       # sent with a shot: the face first, then the marked photos
MIN_CANDIDATES, MAX_CANDIDATES, DEFAULT_CANDIDATES = 1, 6, 4

FACE_CODE = "SHOT_01"
SHOT_WIDTH, SHOT_HEIGHT = 864, 1152
ASPECT = "3:4"
IMAGE_SIZE = "1K"
STUCK_MINUTES = 15

DESCRIBE_TEMPERATURE = 0.4
DESCRIBE_MAX_TOKENS = 4096


def clean_text(value: Any, limit: int) -> str:
    """One line: collapses whitespace."""
    return " ".join(str(value or "").split())[:limit]


def clean_lines(text: str) -> str:
    """Multi-line text: spaces collapsed, lines trimmed, at most one empty line in a row."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_identity(raw: Any) -> str:
    """The identity as stored: from a model answer (a dict or a string) or the editor.
    Spaces collapsed, lines trimmed, at most one empty line in a row, cut to 6000."""
    if isinstance(raw, dict):
        raw = raw.get("identity") or raw.get("description") or raw.get("text") or ""
    return clean_lines(str(raw or ""))[:MAX_IDENTITY].strip()


def clean_brief(raw: Any) -> str:
    return clean_lines(str(raw or ""))[:MAX_BRIEF].strip()


def one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def publish(what: str, **data: Any) -> None:
    events.publish("avatars.updated", {"what": what, **data})
