"""Names, limits and small helpers shared by the parts of the text module (06)."""

from __future__ import annotations

import logging
import re
from typing import Any

from vf.core import events
from vf.core.errors import AppError

log = logging.getLogger("vf.text")

# prompt files (app/prompts/text/…)
PROMPT_PLACEMENT = "text.placement"
PROMPT_WRITE = "text.write"
PROMPT_VARIANTS = "text.variants"
PROMPT_HUMANIZE = "text.humanize"
PROMPT_BACKGROUND = "text.background"

# journal purposes
PURPOSE_PLACEMENT = "text_placement"
PURPOSE_WRITE = "text_write"
PURPOSE_VARIANTS = "text_variants"
PURPOSE_HUMANIZE = "text_humanize"
PURPOSE_BACKGROUND = "text_background"

# roles of the model registry
ROLE_PLACEMENT = "text_placement"
ROLE_TEXT = "image_text"

REF_DESIGN = "text_design"          # journal ref, spend card, job ref
JOB_BACKGROUND = "text.background"  # the job that draws new backgrounds
USAGE_TYPE = "text"                 # media library: a picture is used by a design

# files.source_type of what this module stores
SOURCE_DESIGN = "text_design"        # a saved picture with the words on it
SOURCE_BACKGROUND = "text_background"  # a background drawn on the «Generate» tab
SOURCE_SHEET = "text_font_sheet"     # the brand's type specimen (service file)
SOURCE_FONT = "brand_asset"          # a Google font added to a kit (the brand module's own type)

TEXT_ROLES = ("headline", "body", "accent")
SIZES = ("sm", "md", "lg", "xl")
# font size as a share of the picture height (ported from factory slide_text_placement)
SIZE_RATIOS = {"sm": 0.032, "md": 0.045, "lg": 0.060, "xl": 0.082}
ALIGNS = ("left", "center", "right")
VERTICALS = ("top", "middle", "bottom")
LAYER_TYPES = ("text", "logo", "shape")
SHAPES = ("rect", "ellipse")
DEFAULT_SIZE = {"headline": "xl", "body": "md", "accent": "lg"}

# The language goes to the model as a full name: "uk" alone reads as the United Kingdom.
LANGUAGES = {"ru": "Russian", "uk": "Ukrainian", "en": "English"}
DEFAULT_LANGUAGE = "en"

MAX_LAYERS = 30
MAX_TEXTS = 8              # blocks of words on one picture
MAX_TEXT = 600             # one block
MAX_VARIANTS = 4           # «N variants of one line» in one press
MAX_BACKGROUNDS = 4        # «Generate» tab: pictures in one press
MAX_PROMPT = 4000          # the background prompt
MAX_NOTE = 1000            # what the person adds to a text request
MAX_HUMANIZE_CHARS = 8000  # all the blocks sent to «Make it sound human» together
MAX_LAYOUT_TITLE = 80
MAX_LAYOUTS = 60           # the person's own layouts
PLACEMENT_SIDE = 512       # the picture goes to the vision model at most this big
RENDER_MAX_SIDE = 4096     # the saved picture is at most this big

_TERMINAL_DOTS = ".…"


def clean_line(value: Any, limit: int) -> str:
    """One line: spaces collapsed, cut to ``limit``."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def clean_block(value: Any, limit: int) -> str:
    """Several lines: spaces at the ends and empty lines at the ends dropped, cut to ``limit``."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value or "").replace("\r", "").split("\n")]
    return "\n".join(lines).strip("\n")[:limit].strip()


def clean_overlay_text(value: Any) -> str:
    """Words the model wrote for a picture: trimmed, and no full stop at the end of a line.

    Ported from factory ``services/text_hygiene.py``: a dot at the end of a headline
    reads as a stray mark on the design. Question and exclamation marks stay.
    Applied to the model's answers only, never to what the person typed."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    lines = [line.rstrip().rstrip(_TERMINAL_DOTS).rstrip() for line in value.replace("\r", "").splitlines()]
    return "\n".join(lines).strip()


def language(value: Any) -> str:
    code = str(value or "").strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def flag(body: dict, name: str, default: bool = False) -> bool:
    value = body.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise AppError("bad_request", 400, "A switch is true or false", field=name)
    return value


def count(value: Any, *, low: int = 1, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise AppError("bad_request", 400, "A number is expected", min=low, max=high) from None
    if not low <= n <= high:
        raise AppError("bad_request", 400, "The number is out of range", min=low, max=high)
    return n


def hex_color(value: Any, default: str | None = "#FFFFFF") -> str | None:
    """``#RRGGBB`` (upper case); ``#RGB`` is widened; anything else gives ``default``."""
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.upper()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", text):
        return ("#" + "".join(ch * 2 for ch in text[1:])).upper()
    return default


def rgb(value: str) -> tuple[int, int, int]:
    value = hex_color(value) or "#FFFFFF"
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def publish(design_id: int, **data: Any) -> None:
    """``text.updated``: the open tool refreshes the design (backgrounds, saves)."""
    events.publish("text.updated", {"design_id": design_id, **data})


__all__ = [
    "ALIGNS", "JOB_BACKGROUND", "LANGUAGES", "LAYER_TYPES", "MAX_BACKGROUNDS", "MAX_LAYERS", "MAX_TEXTS",
    "MAX_VARIANTS", "REF_DESIGN", "SIZES", "SIZE_RATIOS", "TEXT_ROLES", "USAGE_TYPE", "VERTICALS",
    "clean_block", "clean_line", "clean_overlay_text", "count", "flag", "hex_color", "language", "publish", "rgb",
]
