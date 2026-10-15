"""Style wording slots and text-zone maps — the pure half of the library.

A style is written once and reused for every brand: the parts that change from
work to work are ``{{name}}`` slots, optionally with a fallback —
``{{brand|SALT & STONE}}``. Values are typed when the style is applied and the
real text is put together on the server (``service.render_style``).

The grammar is the factory one (``api/services/prompt_presets.py`` and
``frontend/utils/promptVariables.js``) so the ported library reads the same.
It is deliberately not the grammar of prompt files (``vf.core.prompts``): a
style is substituted in full before its text joins a prompt, and the result is
never rendered a second time.
"""

from __future__ import annotations

import json
import re
from typing import Any

from vf.core.errors import AppError

VARIABLE_RE = re.compile(r"\{\{\s*([^{}|]{1,60}?)\s*(?:\|\s*([^{}]{0,200}?)\s*)?\}\}")

MAX_PROMPT_VARIABLES = 20
MAX_VALUE_CHARS = 1000
MAX_EXTRA_CHARS = 1000          # the person's own words added after the style
MAX_STYLE_CHARS = 4000          # a filled style never grows past this (factory cap)
MAX_TEXT_ZONES_CHARS = 40000

# Slot vocabulary of the shipped library and the field each slot gets
# (factory PROMPT_VARIABLES). Anything else is a plain text field, or a colour
# field when its name says "colour".
VARIABLE_TYPES: dict[str, str] = {
    "subject": "subject",
    "subject_appearance": "text",
    "subject_color": "color",
    "design_on_subject": "text",
    "secondary_subject": "subject",
    "additional_elements": "subjects",
    "action": "text",
    "clothing": "subject",
    "environment": "subject",
    "background_color": "color",
    "effect": "text",
    "brand": "brand",
    "text_on_subject": "text",
}
# Word boundaries are "not a letter" (underscore and digits count as breaks), so
# `accent_color` is a colour and `discolour` is not.
_COLOR_NAME = re.compile(
    r"(?:^|[\W\d_])(?:colou?rs?|hex|accents?|цвет[^\W\d_]*|колір|кольор[^\W\d_]*|акцент[^\W\d_]*)(?:[\W\d_]|$)",
    re.IGNORECASE)

_TIDY = (
    (re.compile(r"[«\"“]\s*[»\"”]"), ""),
    (re.compile(r"[ \t]{2,}"), " "),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r",\s*(?=[,.])"), ""),
    (re.compile(r"[ \t]+$", re.MULTILINE), ""),
)


def variable_key(name: Any) -> str:
    """``{{Brand}}`` and ``{{brand}}`` are one slot — one value fills both."""
    return str(name or "").strip().lower()


def variable_type(name: str) -> str:
    slot = re.sub(r"[\s-]+", "_", variable_key(name).replace("’", "'"))
    if slot in VARIABLE_TYPES:
        return VARIABLE_TYPES[slot]
    return "color" if _COLOR_NAME.search(name or "") else "text"


def extract_variables(prompt: str | None) -> list[dict]:
    """The slots of a style, first occurrence wins: ``[{key, name, default, type}]``."""
    out: list[dict] = []
    seen: set[str] = set()
    for match in VARIABLE_RE.finditer(str(prompt or "")):
        name = (match.group(1) or "").strip()
        key = variable_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "name": name, "default": (match.group(2) or "").strip(),
                    "type": variable_type(name)})
        if len(out) >= MAX_PROMPT_VARIABLES:
            break
    return out


def tidy(text: str) -> str:
    """Sweep what a blank slot leaves behind: a lone comma, a doubled space, empty quotes."""
    for pattern, replacement in _TIDY:
        text = pattern.sub(replacement, text)
    return text.strip()


def fill_variables(prompt: str | None, values: dict[str, Any] | None = None) -> str:
    """Substitute slots; a blank or missing value falls back to the slot's default."""
    typed = {variable_key(k): v for k, v in (values or {}).items()}

    def _sub(match: re.Match) -> str:
        value = str(typed.get(variable_key(match.group(1))) or "").strip()[:MAX_VALUE_CHARS]
        return value or (match.group(2) or "").strip()

    return tidy(VARIABLE_RE.sub(_sub, str(prompt or "")))


def clean_values(raw: Any) -> dict[str, str]:
    """Values as sent by a caller: a ``{key: value}`` dict or the factory ``[{key, value}]`` list."""
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [(v.get("key"), v.get("value")) for v in raw if isinstance(v, dict)]
    else:
        items = []
    for key, value in items:
        k = variable_key(key)
        if k and len(out) < MAX_PROMPT_VARIABLES:
            out[k] = "" if value is None else str(value)[:MAX_VALUE_CHARS]
    return out


# ── style references ────────────────────────────────────────────────────────
# A brief keeps a *reference* to a style, not its text:
#   {"preset": 42, "title": "...", "vars": [{"key": "brand", "name": "Brand", "value": "SALT"}], "extra": "..."}
# The text is put together on the server when the prompt is assembled.

REF_PREFIX = '{"preset":'


def is_style_ref(value: Any) -> bool:
    return isinstance(value, str) and value.lstrip().startswith(REF_PREFIX)


def parse_style_ref(value: Any) -> dict | None:
    """A reference as a dict (a JSON string is parsed too); None when it is not one."""
    ref = value
    if isinstance(value, str):
        if not is_style_ref(value):
            return None
        try:
            ref = json.loads(value)
        except ValueError:
            return None
    if not isinstance(ref, dict):
        return None
    try:
        preset_id = int(ref.get("preset"))
    except (TypeError, ValueError):
        return None
    if preset_id <= 0:
        return None
    variables = []
    for item in ref.get("vars") or []:
        if not isinstance(item, dict) or not variable_key(item.get("key")):
            continue
        key = variable_key(item.get("key"))
        variables.append({"key": key, "name": str(item.get("name") or key),
                          "value": str(item.get("value") or "")[:MAX_VALUE_CHARS]})
    return {"preset": preset_id, "title": str(ref.get("title") or "")[:200],
            "vars": variables[:MAX_PROMPT_VARIABLES],
            "extra": str(ref.get("extra") or "")[:MAX_EXTRA_CHARS].strip()}


def make_style_ref(preset: dict, values: dict[str, str] | None = None, extra: str = "") -> str:
    """The reference a brief stores for this style and these values (``preset`` is the first key)."""
    values = clean_values(values or {})
    payload: dict[str, Any] = {"preset": int(preset["id"]), "title": str(preset.get("title") or "")[:200]}
    payload["vars"] = [{"key": v["key"], "name": v["name"], "value": values.get(v["key"], "")}
                       for v in extract_variables(preset.get("prompt"))]
    extra = str(extra or "")[:MAX_EXTRA_CHARS].strip()
    if extra:
        payload["extra"] = extra
    return json.dumps(payload, ensure_ascii=False)


# ── text zones ──────────────────────────────────────────────────────────────

def parse_text_zones(raw: Any) -> dict | None:
    """A zone map from the editor (JSON text) or a caller (dict); None clears it.

    Boxes are percentages of the canvas. Errors are codes the browser translates.
    """
    if raw is None:
        return None
    value = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if len(text) > MAX_TEXT_ZONES_CHARS:
            raise AppError("text_zones_too_large", 422, "text zones are too large", max_chars=MAX_TEXT_ZONES_CHARS)
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise AppError("text_zones_invalid_json", 422, "text zones are not valid JSON",
                           line=getattr(exc, "lineno", None)) from None
    if not isinstance(value, dict) or ("zones" in value and not isinstance(value["zones"], list)):
        raise AppError("text_zones_not_an_object", 422, "text zones must be an object with a zones list")
    if len(json.dumps(value, ensure_ascii=False)) > MAX_TEXT_ZONES_CHARS:
        raise AppError("text_zones_too_large", 422, "text zones are too large", max_chars=MAX_TEXT_ZONES_CHARS)
    return value


def count_text_zones(value: Any) -> int:
    return len(value["zones"]) if isinstance(value, dict) and isinstance(value.get("zones"), list) else 0
