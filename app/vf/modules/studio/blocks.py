"""Prompt blocks of a frame: the catalog, which blocks apply, and their text.

A block is one layer file ``PROMPT_BLOCK_<CODE>`` (module 07). The work keeps a
tumbler per block; a block that is off sends nothing — neither its words nor the
pictures that belong to it. A block that does not apply (no brand, no subjects…)
is shown greyed out with the reason, and sends nothing either.

Ported from factory ``api/services/prompt_composer.py`` (catalog ≈347–426); the
post-only blocks (topic, goal, caption) are not carried over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vf.modules import library

# (code, on by default) in the order the texts are joined.
CATALOG: tuple[tuple[str, bool], ...] = (
    ("output_size", True),
    ("language", False),
    ("brand_colors", True),
    ("brand_fonts", False),
    ("tone_of_voice", True),
    ("logo", True),
    ("project_references", True),
    ("task_attachments", True),
    ("subjects", True),
    ("identity_assets", False),
    ("image_style", True),
    ("photo_style", True),
    ("slide_position", True),
    ("slide_text", False),
    ("draw_text", True),
    ("no_lettering", True),
    ("quality", True),
    ("variant_diversity", True),
    ("feedback", True),
)
DEFAULTS = dict(CATALOG)
CODES = tuple(code for code, _ in CATALOG)

LANGUAGE_NAMES = {"ru": "Russian", "uk": "Ukrainian", "en": "English"}

# Brand font categories in words the image model understands (factory prompt_composer).
FONT_DESCRIPTORS = {
    "serif": "serif (classic, editorial)",
    "sans": "sans-serif (clean, modern, geometric)",
    "display": "display / decorative (bold, expressive)",
    "handwriting": "handwritten / script (personal, casual)",
    "mono": "monospace (technical, terminal-like)",
}


@dataclass
class Facts:
    """What a frame's blocks are made from (collected by ``compose``)."""

    text_mode: str = "none"
    words: list[dict] = field(default_factory=list)      # [{role, text}]
    brand: dict | None = None
    references: int = 0                                  # pictures in the references part (anchor too)
    attachments: int = 0
    subjects: list[dict] = field(default_factory=list)   # describe_subjects()
    style: str | None = None
    photo_style: str | None = None
    position: int = 1
    frame_count: int = 1
    size: tuple[int, int] | None = None                  # configured output size (1K pictures only)
    large: bool = False                                  # 2K/4K: the model's own size is kept, no output size
    variant: int = 1
    feedback: str = ""
    language: str = "en"


def normalize_toggles(value: Any) -> dict[str, bool]:
    """``{code: bool}`` for known codes only."""
    if not isinstance(value, dict):
        return {}
    return {code: bool(on) for code, on in value.items() if code in DEFAULTS}


def toggles(saved: dict | None) -> dict[str, bool]:
    """Every block with its on/off state: what the person set, else the default."""
    saved = saved or {}
    return {code: bool(saved.get(code, default)) for code, default in CATALOG}


# ── formatting of data lines (kept in code: these are lists, not wording) ──

def words_text(words: list[dict]) -> str:
    """Words to draw, block by block: ``[role]\\ntext`` joined by blank lines."""
    out = []
    for block in words or []:
        text = str(block.get("text") or "").strip()
        if text:
            out.append(f"[{block.get('role') or 'body'}]\n{text}")
    return "\n\n".join(out)


def plain_words(words: list[dict]) -> str:
    return "\n".join(str(b.get("text") or "").strip() for b in words or [] if str(b.get("text") or "").strip())


def colors_text(colors: list[dict]) -> str:
    lines = []
    for c in colors or []:
        hex_value = str(c.get("hex") or "").strip()
        if not hex_value:
            continue
        label = str(c.get("label") or "").strip()
        lines.append(f"  - {hex_value} ({label})" if label else f"  - {hex_value}")
    return "\n".join(lines)


def fonts_text(fonts: list[dict]) -> str:
    seen: list[str] = []
    for f in fonts or []:
        category = f.get("category")
        if category in FONT_DESCRIPTORS and category not in seen:
            seen.append(category)
    return "\n".join(f"  - {FONT_DESCRIPTORS[c]}" for c in seen)


def subjects_text(subjects: list[dict]) -> str:
    lines = []
    for s in subjects or []:
        head = f"  - {s.get('name') or ''} [{s.get('kind') or 'object'}]"
        description = " ".join(str(s.get("description") or "").split())
        lines.append(f"{head}: {description}" if description else head)
    return "\n".join(lines)


def assets_text(elements: list[dict]) -> str:
    lines = []
    for e in elements or []:
        title = " ".join(str(e.get("name") or e.get("note") or "").split())
        lines.append(f"  - {e.get('kind') or 'element'}: {title}" if title else f"  - {e.get('kind') or 'element'}")
    return "\n".join(lines)


# ── applicability and text ──────────────────────────────────────────────────

def _reason(code: str, f: Facts) -> str | None:
    """Why a block does not apply to this frame, or None when it does."""
    brand = f.brand or {}
    drawn = f.text_mode == "model"
    checks = {
        "output_size": "large_size" if f.large else (None if f.size else "no_size"),
        "language": None if drawn else "text_not_drawn",
        "brand_colors": "no_brand" if not f.brand else (None if colors_text(brand.get("colors")) else "no_colors"),
        "brand_fonts": "no_brand" if not f.brand else (None if fonts_text(brand.get("fonts")) else "no_fonts"),
        "tone_of_voice": "no_brand" if not f.brand else (None if (brand.get("tone") or "").strip() else "no_tone"),
        "logo": "no_brand" if not f.brand else (None if _logo(brand) else "no_logo"),
        "project_references": None if f.references else "no_references",
        "task_attachments": None if f.attachments else "no_attachments",
        "subjects": None if f.subjects else "no_subjects",
        "identity_assets": "no_brand" if not f.brand else (None if elements_of(brand) else "no_elements"),
        "image_style": None if f.style else "no_style",
        "photo_style": None if f.photo_style else "no_photo_style",
        "slide_position": "single_frame" if f.frame_count < 2 else ("text_drawn" if drawn else None),
        "slide_text": ("no_overlay" if f.text_mode != "overlay" else
                       (None if plain_words(f.words) else "no_words")),
        "draw_text": None if drawn else "text_not_drawn",
        "no_lettering": "text_drawn" if drawn else None,
        "quality": None,
        "variant_diversity": None if f.variant > 1 else "first_version",
        "feedback": None if f.feedback.strip() else "no_feedback",
    }
    return checks.get(code)


def _logo(brand: dict) -> dict | None:
    return next((x for x in brand.get("logos") or [] if x.get("file_id")), None)


def elements_of(brand: dict | None) -> list[dict]:
    return [e for e in (brand or {}).get("elements") or [] if e.get("file_id")]


def logo_of(brand: dict | None) -> dict | None:
    return _logo(brand or {})


def catalog(saved: dict | None, f: Facts) -> list[dict]:
    """For the panel: ``[{code, on, default, applies, reason}]`` in prompt order."""
    on = toggles(saved)
    out = []
    for code, default in CATALOG:
        reason = _reason(code, f)
        out.append({"code": code, "on": on[code], "default": default, "applies": reason is None, "reason": reason})
    return out


def active(saved: dict | None, f: Facts) -> list[str]:
    """Codes that are on and apply: these and only these go to the model."""
    on = toggles(saved)
    return [code for code in CODES if on[code] and _reason(code, f) is None]


def _values(code: str, f: Facts) -> dict:
    brand = f.brand or {}
    if code == "output_size":
        return {"width": f.size[0], "height": f.size[1]} if f.size else {}
    return {
        "language": {"language_name": LANGUAGE_NAMES.get(f.language, "English")},
        "brand_colors": {"colors": colors_text(brand.get("colors"))},
        "brand_fonts": {"fonts": fonts_text(brand.get("fonts"))},
        "tone_of_voice": {"tone": (brand.get("tone") or "").strip()},
        "project_references": {"count": f.references},
        "task_attachments": {"count": f.attachments},
        "subjects": {"subject_lines": subjects_text(f.subjects)},
        "identity_assets": {"assets": assets_text(elements_of(brand))},
        "image_style": {"style": f.style or ""},
        "photo_style": {"photo_style": f.photo_style or ""},
        "slide_position": {"slide_index": f.position, "slide_count": f.frame_count},
        "slide_text": {"slide_text": plain_words(f.words)},
        "draw_text": {"words": words_text(f.words)},
        "variant_diversity": {"variant_number": f.variant},
        "feedback": {"feedback": f.feedback.strip()},
    }.get(code, {})


def layer_code(code: str) -> str:
    """The layer file of a block: ``quality`` → ``PROMPT_BLOCK_QUALITY``."""
    return f"PROMPT_BLOCK_{code.upper()}"


def render(codes: list[str], f: Facts) -> list[str]:
    """The texts of the given blocks, in catalog order."""
    out = []
    for code in CODES:
        if code not in codes:
            continue
        text = library.render_layer(layer_code(code), _values(code, f)).strip()
        if text:
            out.append(text)
    return out
