"""Words with timings -> an ASS subtitle track (ported from factory
``api/services/video/subtitles.py``, presets now live in ``subtitle_presets``).

Sizes in a preset are fractions of the frame and are multiplied out against
the frame being rendered; PlayResX/PlayResY are the real frame size, so one ASS
unit is one pixel. Words are stored once (one timing per word) and grouped into
lines here, at render time, so switching "line" / "word" mode loses nothing.

The word being spoken is lit up by one event per word that carries the whole
line (not by karaoke ``\\k``, which colors everything already sung).
"""

from __future__ import annotations

from typing import Any

from vf.core import db
from vf.modules.clip.state import hex_color

HOLD_AFTER_S = 0.35   # a caption stays this long after its last word
MAX_GAP_S = 0.8       # a longer pause between words starts a new line
MIN_EVENT_S = 0.06    # shorter events are a flicker

POSITION_ALIGNMENT = {"bottom": 2, "middle": 5, "top": 8}

PRESET_FIELDS = (
    "id", "code", "name", "description", "mode", "font_family", "font_size_ratio", "bold", "italic", "uppercase",
    "primary_color", "highlight_color", "outline_color", "back_color", "back_opacity", "outline_ratio",
    "shadow_ratio", "border_style", "alignment", "margin_v_ratio", "margin_h_ratio", "max_words_per_line",
    "use_brand", "sort",
)

FALLBACK_PRESET: dict[str, Any] = {
    "id": None, "code": "clean", "name": "Clean", "description": "", "mode": "line", "font_family": "DejaVu Sans",
    "font_size_ratio": 0.045, "bold": True, "italic": False, "uppercase": False, "primary_color": "#FFFFFF",
    "highlight_color": "#FFE066", "outline_color": "#000000", "back_color": "#000000", "back_opacity": 0.0,
    "outline_ratio": 0.08, "shadow_ratio": 0.04, "border_style": 1, "alignment": 2, "margin_v_ratio": 0.12,
    "margin_h_ratio": 0.06, "max_words_per_line": 4, "use_brand": False, "sort": 0,
}


# ── presets ─────────────────────────────────────────────────────────────────

def _preset_row(row: dict) -> dict:
    out = {k: row.get(k) for k in PRESET_FIELDS}
    for key in ("bold", "italic", "uppercase", "use_brand"):
        out[key] = bool(out[key])
    return out


def list_presets() -> list[dict]:
    return [_preset_row(r) for r in db.fetch_all("SELECT * FROM subtitle_presets ORDER BY sort, id")]


def get_preset(code: str | None) -> dict:
    """The preset by code; the first one (or the built-in "clean") when it is gone."""
    row = None
    if code:
        row = db.fetch_one("SELECT * FROM subtitle_presets WHERE code = ?", (code,))
    if row is None:
        row = db.fetch_one("SELECT * FROM subtitle_presets ORDER BY sort, id LIMIT 1")
    return _preset_row(row) if row else dict(FALLBACK_PRESET)


# ── colors ──────────────────────────────────────────────────────────────────

def _rgb(value: Any, default: str) -> tuple[int, int, int]:
    h = hex_color(value, default)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luma(value: Any) -> float:
    r, g, b = _rgb(value, "#000000")
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def ass_color(value: Any, *, alpha: float = 1.0, default: str = "#FFFFFF") -> str:
    """#RRGGBB -> &HAABBGGRR (ASS writes colors backwards; alpha 00 = opaque)."""
    r, g, b = _rgb(value, default)
    a = int(round((1.0 - max(0.0, min(1.0, alpha))) * 255))
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


def inline_color(value: Any, default: str = "#FFFFFF") -> str:
    """Color for an inline ``\\c`` tag: &HBBGGRR&."""
    r, g, b = _rgb(value, default)
    return f"&H{b:02X}{g:02X}{r:02X}&"


# ── brand ───────────────────────────────────────────────────────────────────

def brand_font(brand: dict | None) -> dict | None:
    """The brand font to use for captions and new text: a headline/display font
    with a file first, else the first font with a file."""
    fonts = [f for f in (brand or {}).get("fonts") or [] if f.get("file_id") and f.get("family")]
    for f in fonts:
        if (f.get("category") or "") == "display":
            return f
    return fonts[0] if fonts else None


def resolve_brand(preset: dict, brand: dict | None) -> tuple[dict, list[int]]:
    """Fold the brand kit into a preset that asks for it. The text stays light
    with a dark outline for legibility; the brand gives the highlight color,
    the outline (its darkest color when dark enough) and the font.
    Returns (preset, font file ids to hand to ``burn``)."""
    if not preset.get("use_brand") or not brand:
        return preset, []
    merged = dict(preset)
    font_ids: list[int] = []
    font = brand_font(brand)
    if font:
        merged["font_family"] = font["family"]
        font_ids.append(int(font["file_id"]))
    hexes = [c.get("hex") for c in brand.get("colors") or [] if c.get("hex")]
    if hexes:
        merged["highlight_color"] = hexes[0]
        darkest = min(hexes, key=luma)
        merged["outline_color"] = darkest if luma(darkest) < 0.45 else "#000000"
    return merged, font_ids


def apply_position(preset: dict, position: str | None) -> dict:
    if not position or position not in POSITION_ALIGNMENT:
        return preset
    out = dict(preset)
    out["alignment"] = POSITION_ALIGNMENT[position]
    if position == "middle":
        out["margin_v_ratio"] = 0.0
    elif not out.get("margin_v_ratio"):
        out["margin_v_ratio"] = 0.1
    return out


# ── words ───────────────────────────────────────────────────────────────────

def group_lines(words: list[dict], max_words: int) -> list[list[dict]]:
    """Cut the word stream into on-screen lines: by word count, by a pause longer
    than MAX_GAP_S and after sentence-final punctuation."""
    limit = max(1, int(max_words or 1))
    lines: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            ends_sentence = current[-1]["text"][-1:] in ".!?…"
            if len(current) >= limit or gap > MAX_GAP_S or ends_sentence:
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


# ── ASS ─────────────────────────────────────────────────────────────────────

def ts(seconds: float) -> str:
    """h:mm:ss.cc"""
    cs = int(round(max(0.0, float(seconds)) * 100))
    hours, rest = divmod(cs, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cents = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cents:02d}"


def escape(text: str) -> str:
    """Braces open override blocks and a backslash starts a tag in ASS."""
    return (str(text).replace("\\", "∖").replace("{", "(").replace("}", ")")
            .replace("\r\n", "\\N").replace("\n", "\\N"))


def style_line(name: str, preset: dict, width: int, height: int) -> str:
    """A [V4+ Styles] line with every ratio multiplied out against this frame.
    BorderStyle 3 (box) draws its box in OutlineColour, so a boxed preset's
    back color and opacity land there."""
    size = max(8, int(round(float(preset.get("font_size_ratio") or 0.045) * height)))
    outline = round(float(preset.get("outline_ratio") or 0) * size, 1)
    shadow = round(float(preset.get("shadow_ratio") or 0) * size, 1)
    margin_v = int(round(float(preset.get("margin_v_ratio") or 0) * height))
    margin_h = int(round(float(preset.get("margin_h_ratio") or 0) * width))
    border_style = 3 if int(preset.get("border_style") or 1) == 3 else 1
    primary = ass_color(preset.get("primary_color"), default="#FFFFFF")
    if border_style == 3:
        opacity = preset.get("back_opacity")
        outline_c = ass_color(preset.get("back_color"), alpha=0.65 if opacity is None else float(opacity),
                              default="#000000")
        back_c = ass_color(preset.get("back_color"), alpha=0.0, default="#000000")
    else:
        outline_c = ass_color(preset.get("outline_color"), default="#000000")
        back_c = ass_color(preset.get("back_color"), alpha=0.6, default="#000000")
    bold = -1 if preset.get("bold") else 0
    italic = -1 if preset.get("italic") else 0
    alignment = int(preset.get("alignment") or 2)
    if alignment not in range(1, 10):
        alignment = 2
    font = str(preset.get("font_family") or "DejaVu Sans").replace(",", " ")
    return (f"Style: {name},{font},{size},{primary},{primary},{outline_c},{back_c},"
            f"{bold},{italic},0,0,100,100,0,0,{border_style},{outline},{shadow},"
            f"{alignment},{margin_h},{margin_h},{margin_v},1")


def word_events(items: list[dict], upper: bool) -> list[tuple[float, float, str]]:
    """One word on screen at a time, held until the next one starts."""
    events = []
    for i, word in enumerate(items):
        if i + 1 < len(items):
            gap = items[i + 1]["start"] - word["end"]
            end = items[i + 1]["start"] if gap <= MAX_GAP_S else word["end"] + HOLD_AFTER_S
        else:
            end = word["end"] + HOLD_AFTER_S
        text = word["text"].upper() if upper else word["text"]
        events.append((word["start"], end, escape(text)))
    return events


def line_events(items: list[dict], preset: dict, upper: bool) -> list[tuple[float, float, str]]:
    """A short line on screen with the spoken word lit up inside it."""
    events = []
    lines = group_lines(items, int(preset.get("max_words_per_line") or 4))
    primary = inline_color(preset.get("primary_color"), "#FFFFFF")
    highlight = inline_color(preset.get("highlight_color"), "#FFD400")
    lit = hex_color(preset.get("highlight_color"), "#FFD400") != hex_color(preset.get("primary_color"), "#FFFFFF")
    for li, line in enumerate(lines):
        line_end = line[-1]["end"] + HOLD_AFTER_S
        if li + 1 < len(lines):
            line_end = min(line_end, lines[li + 1][0]["start"])
        for wi, word in enumerate(line):
            end = line[wi + 1]["start"] if wi + 1 < len(line) else line_end
            parts = []
            for pi, other in enumerate(line):
                text = escape(other["text"].upper() if upper else other["text"])
                parts.append(f"{{\\c{highlight}}}{text}{{\\c{primary}}}" if pi == wi and lit else text)
            events.append((word["start"], end, " ".join(parts)))
    return events


def subtitle_dialogues(words: list[dict], preset: dict, *, mode: str | None, end_at: float | None,
                       style: str = "Sub", layer: int = 0) -> list[str]:
    """Dialogue lines for words already in output time."""
    if not words:
        return []
    resolved = (mode or preset.get("mode") or "line").lower()
    upper = bool(preset.get("uppercase"))
    events = word_events(words, upper) if resolved == "word" else line_events(words, preset, upper)
    out = []
    for start, end, text in events:
        start = max(0.0, start)
        if end_at is not None:
            if start >= end_at:
                continue
            end = min(end, end_at)
        if end - start < MIN_EVENT_S:
            end = start + MIN_EVENT_S
        out.append(f"Dialogue: {layer},{ts(start)},{ts(end)},{style},,0,0,0,,{text}")
    return out


def document(width: int, height: int, styles: list[str], dialogues: list[str]) -> str:
    """The whole ASS file; "" when there is nothing to draw."""
    if not dialogues:
        return ""
    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    return header + "\n" + "\n".join(dialogues) + "\n"


def build_ass(words: list[dict], preset: dict, *, width: int, height: int, mode: str | None = None,
              end_at: float | None = None) -> str:
    """Subtitles alone (words in output time) -> ASS text."""
    dialogues = subtitle_dialogues(words, preset, mode=mode, end_at=end_at)
    return document(width, height, [style_line("Sub", preset, width, height)], dialogues)
