"""Names, limits and settings shared by the parts of the ideas module."""

from __future__ import annotations

import re
from datetime import datetime

from vf.core import settings

# prompt files (app/prompts/ideas/…) and layers (app/prompts/layers/ideas/…)
PROMPT_IDEAS = "ideas.shot_ideas"
PROMPT_RESEARCH = "ideas.research"
PROMPT_FRAME = "ideas.frame_idea"

# journal purposes
PURPOSE_IDEAS = "shot_ideas"
PURPOSE_RESEARCH = "shot_research"
PURPOSE_FRAME = "shot_idea_frame"

# roles of the model registry
ROLE_IDEAS = "shot_ideas"
ROLE_RESEARCH = "research"

REF_SET = "ideas_set"          # journal ref, spend card, job ref
JOB_WRITE = "ideas.write"      # the job that writes a set
MESSAGE_KIND = "ideas.concept"  # the chat message that shows a set
USAGE_TYPE = "ideas"           # media library: a picture is used by a set's brief

STATUSES = ("running", "done", "error", "cancelled")

# The label language goes to the model as a full name: "uk" alone reads as the United Kingdom.
LANGUAGES = {"ru": "Russian", "uk": "Ukrainian", "en": "English"}
DEFAULT_LANGUAGE = "en"

MAX_COUNT = 10                 # frames in a set (0 = the model decides)
MAX_PRODUCT_REFS = 6
MAX_VISUAL_REFS = 6
REF_SIDE = 1024                # brief pictures go to the model at most this big

MAX_NICHE = 200
MAX_FIELD = 1200
MAX_NOTE = 600
MAX_CONCEPT_NAME = 80
MAX_DIRECTION = 2000
MAX_TITLE = 80
MAX_PROMPT = 3000

MAX_RESEARCH_NICHE = 120
MAX_RESEARCH_PLATFORM = 40
MAX_RESEARCH_TEXT = 9000
MAX_SOURCES = 12
RESEARCH_HEADING = "NICHE RESEARCH — what the leading companies of this category are doing now"

settings.define("ideas.research_cache_days", 14, group="ideas", kind="int", min=0, max=365,
                label_key="ideas.settings.researchDays.label", help_key="ideas.settings.researchDays.help")


def clean_line(value: object, limit: int) -> str:
    """One line: spaces collapsed, cut to ``limit``."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def clean_block(value: object, limit: int) -> str:
    """Several lines: empty lines and spaces at the ends dropped, cut to ``limit``."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value or "").replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line)[:limit].strip()


def key_of(text: object) -> str:
    """A cache key: lower case, spaces collapsed."""
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def stamp(moment: datetime) -> str:
    """The same text form as ``db.now()`` (so it can be compared with created_at)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def cache_days() -> int:
    try:
        return max(0, int(settings.get("ideas.research_cache_days") or 0))
    except (TypeError, ValueError):
        return 0
