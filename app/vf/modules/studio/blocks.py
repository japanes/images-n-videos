"""Prompt blocks of a frame: which blocks apply, and their text.

A block is one layer file ``PROMPT_BLOCK_<CODE>`` (module 07). There are no
switches: a block goes to the model when the frame has what it is made from (a
brand, subjects, a photo style…) and sends nothing otherwise. Style, wording and
lettering are written by the person in the brief itself.

Ported from factory ``api/services/prompt_composer.py`` (catalog ≈347–426); the
post-only blocks (topic, goal, caption) are not carried over.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vf.modules import library

# In the order the texts are joined.
CODES: tuple[str, ...] = (
    "output_size",
    "brand_colors",
    "tone_of_voice",
    "logo",
    "project_references",
    "task_attachments",
    "subjects",
    "photo_style",
    "variant_diversity",
    "feedback",
)


@dataclass
class Facts:
    """What a frame's blocks are made from (collected by ``compose``)."""

    brand: dict | None = None
    references: int = 0                                  # pictures in the references part (anchor too)
    attachments: int = 0
    subjects: list[dict] = field(default_factory=list)   # describe_subjects()
    photo_style: str | None = None
    size: tuple[int, int] | None = None                  # configured output size (1K pictures only)
    large: bool = False                                  # 2K/4K: the model's own size is kept, no output size
    variant: int = 1
    feedback: str = ""


# ── formatting of data lines (kept in code: these are lists, not wording) ──

def colors_text(colors: list[dict]) -> str:
    lines = []
    for c in colors or []:
        hex_value = str(c.get("hex") or "").strip()
        if not hex_value:
            continue
        label = str(c.get("label") or "").strip()
        lines.append(f"  - {hex_value} ({label})" if label else f"  - {hex_value}")
    return "\n".join(lines)


def subjects_text(subjects: list[dict]) -> str:
    lines = []
    for s in subjects or []:
        head = f"  - {s.get('name') or ''} [{s.get('kind') or 'object'}]"
        description = " ".join(str(s.get("description") or "").split())
        lines.append(f"{head}: {description}" if description else head)
    return "\n".join(lines)


# ── applicability and text ──────────────────────────────────────────────────

def _applies(code: str, f: Facts) -> bool:
    brand = f.brand or {}
    checks = {
        "output_size": bool(f.size) and not f.large,
        "brand_colors": bool(colors_text(brand.get("colors"))),
        "tone_of_voice": bool((brand.get("tone") or "").strip()),
        "logo": _logo(brand) is not None,
        "project_references": f.references > 0,
        "task_attachments": f.attachments > 0,
        "subjects": bool(f.subjects),
        "photo_style": bool(f.photo_style),
        "variant_diversity": f.variant > 1,
        "feedback": bool(f.feedback.strip()),
    }
    return checks.get(code, False)


def _logo(brand: dict) -> dict | None:
    return next((x for x in brand.get("logos") or [] if x.get("file_id")), None)


def logo_of(brand: dict | None) -> dict | None:
    return _logo(brand or {})


def active(f: Facts) -> list[str]:
    """Codes that apply to this frame: these and only these go to the model."""
    return [code for code in CODES if _applies(code, f)]


def _values(code: str, f: Facts) -> dict:
    brand = f.brand or {}
    if code == "output_size":
        return {"width": f.size[0], "height": f.size[1]} if f.size else {}
    return {
        "brand_colors": {"colors": colors_text(brand.get("colors"))},
        "tone_of_voice": {"tone": (brand.get("tone") or "").strip()},
        "project_references": {"count": f.references},
        "task_attachments": {"count": f.attachments},
        "subjects": {"subject_lines": subjects_text(f.subjects)},
        "photo_style": {"photo_style": f.photo_style or ""},
        "variant_diversity": {"variant_number": f.variant},
        "feedback": {"feedback": f.feedback.strip()},
    }.get(code, {})


def layer_code(code: str) -> str:
    """The layer file of a block: ``logo`` → ``PROMPT_BLOCK_LOGO``."""
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
