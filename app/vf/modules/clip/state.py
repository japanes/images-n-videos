"""The edit list of a clip project and the time arithmetic around it.

All times are seconds of the SOURCE video: the timeline shows the source, so a
layer or a subtitle word keeps its place when a piece before it is cut out.
Positions and sizes are fractions of the frame, so the same project renders at
any output size (export, small preview, browser preview).

What is kept = ``[trim.start, trim.end]`` minus every ``removed`` range. The
output is those kept segments played one after another; ``to_output`` maps a
source time onto that output time line.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

ASPECTS = ("", "9:16", "1:1", "4:5", "16:9")
ASPECT_SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}
CROP_MODES = ("cover", "pad", "blur")
TRACK_ROLES = ("voice", "music", "sfx")
SUBTITLE_MODES = ("line", "word")
SUBTITLE_POSITIONS = ("", "bottom", "middle", "top")
BUILTIN_FONTS = ("DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono", "Liberation Sans", "Liberation Serif",
                 "Liberation Mono")
DEFAULT_FONT = "DejaVu Sans"

MIN_SEGMENT_S = 0.05     # shorter kept pieces are dropped (a frame or two)
MIN_CLIP_S = 0.1         # trim cannot make the clip shorter than this
MAX_CUTS = 48            # render `split` takes at most 49 points
MAX_REMOVED = 48
MAX_LAYERS = 40
MAX_IMAGE_LAYERS = 16
MAX_TRACKS = 8
MAX_WORDS = 20000
MAX_TEXT = 500
MAX_WORD = 100

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


# ── small coercers ──────────────────────────────────────────────────────────

def _num(value: Any, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        out = default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return round(out, 3)


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def hex_color(value: Any, default: str = "#FFFFFF") -> str:
    m = _HEX.match(str(value or "").strip())
    return f"#{m.group(1).upper()}" if m else default


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")[:limit]


def _id(value: Any) -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:40]
    return raw or uuid.uuid4().hex[:12]


# ── state ───────────────────────────────────────────────────────────────────

def empty_state() -> dict:
    return normalize({}, None)


def normalize(raw: Any, duration: float | None) -> dict:
    """A clean, bounded copy of what the editor sent. Bad values are clamped or
    dropped instead of failing: the editor autosaves often and must not lose
    the rest of the edits because of one odd number."""
    raw = raw if isinstance(raw, dict) else {}
    dur = float(duration) if duration and duration > 0 else None
    top = dur if dur is not None else 24 * 3600.0

    trim_raw = raw.get("trim") if isinstance(raw.get("trim"), dict) else {}
    start = _num(trim_raw.get("start"), 0.0, 0.0, top)
    end_raw = trim_raw.get("end")
    end = None if end_raw is None else _num(end_raw, top, 0.0, top)
    if end is not None and dur is not None and end >= dur - 0.001:
        end = None
    if end is not None and end - start < MIN_CLIP_S:
        end = min(top, start + MIN_CLIP_S)
        if end - start < MIN_CLIP_S:
            start = max(0.0, end - MIN_CLIP_S)
    trim = {"start": start, "end": end}

    cuts = sorted({_num(c, -1, 0.0, top) for c in (raw.get("cuts") or []) if isinstance(c, int | float)})
    cuts = [c for c in cuts if c > MIN_SEGMENT_S and (dur is None or c < dur - MIN_SEGMENT_S)]
    cuts = _dedupe(cuts, MIN_SEGMENT_S)[:MAX_CUTS]

    removed = _merge_ranges([
        (_num(r[0], 0, 0.0, top), _num(r[1], 0, 0.0, top))
        for r in (raw.get("removed") or [])
        if isinstance(r, list | tuple) and len(r) == 2
    ])[:MAX_REMOVED]

    crop_raw = raw.get("crop") if isinstance(raw.get("crop"), dict) else {}
    aspect = crop_raw.get("aspect") if crop_raw.get("aspect") in ASPECTS else ""
    mode = crop_raw.get("mode") if crop_raw.get("mode") in CROP_MODES else "cover"
    crop = {"aspect": aspect, "mode": mode}

    layers: list[dict] = []
    images = 0
    for item in raw.get("layers") or []:
        layer = _layer(item, top)
        if layer is None:
            continue
        if layer["type"] == "image":
            if images >= MAX_IMAGE_LAYERS:
                continue
            images += 1
        layers.append(layer)
        if len(layers) >= MAX_LAYERS:
            break

    return {
        "trim": trim,
        "cuts": cuts,
        "removed": [[a, b] for a, b in removed],
        "crop": crop,
        "layers": layers,
        "subtitles": _subtitles(raw.get("subtitles"), top),
        "audio": _audio(raw.get("audio")),
    }


def _layer(raw: Any, top: float) -> dict | None:
    if not isinstance(raw, dict) or raw.get("type") not in ("text", "image"):
        return None
    start = _num(raw.get("start"), 0.0, 0.0, top)
    end = None if raw.get("end") is None else _num(raw.get("end"), top, 0.0, top)
    if end is not None and end <= start:
        end = min(top, start + MIN_CLIP_S)
    base = {
        "id": _id(raw.get("id")),
        "type": raw["type"],
        "start": start,
        "end": end,
        "x": _num(raw.get("x"), 0.5, 0.0, 1.0),
        "y": _num(raw.get("y"), 0.5, 0.0, 1.0),
        "visible": _bool(raw.get("visible"), True),
    }
    if raw["type"] == "text":
        font = str(raw.get("font") or DEFAULT_FONT).strip()[:100] or DEFAULT_FONT
        base.update({
            "text": _text(raw.get("text"), MAX_TEXT),
            "font": font,
            "font_file_id": _int_or_none(raw.get("font_file_id")),
            "size": _num(raw.get("size"), 0.05, 0.01, 0.3),
            "color": hex_color(raw.get("color"), "#FFFFFF"),
            "bold": _bool(raw.get("bold"), True),
            "italic": _bool(raw.get("italic"), False),
            "outline": _bool(raw.get("outline"), True),
            "plate": _bool(raw.get("plate"), False),
            "plate_color": hex_color(raw.get("plate_color"), "#000000"),
            "plate_opacity": _num(raw.get("plate_opacity"), 0.6, 0.0, 1.0),
        })
        return base
    file_id = _int_or_none(raw.get("file_id"))
    if file_id is None:
        return None
    base.update({
        "file_id": file_id,
        "width": _num(raw.get("width"), 0.2, 0.02, 1.0),
        "opacity": _num(raw.get("opacity"), 1.0, 0.0, 1.0),
    })
    return base


def _subtitles(raw: Any, top: float) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    words = normalize_words(raw.get("words") or [], top)
    mode = raw.get("mode") if raw.get("mode") in SUBTITLE_MODES else None
    position = raw.get("position") if raw.get("position") in SUBTITLE_POSITIONS else ""
    code = re.sub(r"[^a-z0-9_-]", "", str(raw.get("preset_code") or "clean").lower())[:40] or "clean"
    lang = re.sub(r"[^a-z-]", "", str(raw.get("language") or "").lower())[:10] or None
    return {
        "enabled": _bool(raw.get("enabled"), False),
        "preset_code": code,
        "mode": mode,
        "position": position,
        "words": words,
        "transcript_id": _int_or_none(raw.get("transcript_id")),
        "language": lang,
    }


def normalize_words(words: Any, top: float | None = None) -> list[dict]:
    """``[{text|word, start, end}]`` -> sorted ``[{text, start, end}]`` without empty or broken words."""
    out: list[dict] = []
    limit = top if top is not None else 24 * 3600.0
    for raw in words or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("word") or "").strip()[:MAX_WORD]
        if not text:
            continue
        try:
            start = float(raw.get("start") or 0)
            end = float(raw.get("end") or 0)
        except (TypeError, ValueError):
            continue
        start = round(min(max(0.0, start), limit), 3)
        end = round(min(max(start, end), limit), 3)
        if end <= start:
            end = round(start + 0.06, 3)
        out.append({"text": text, "start": start, "end": end})
        if len(out) >= MAX_WORDS:
            break
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out


def _audio(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    tracks: list[dict] = []
    for item in raw.get("tracks") or []:
        if not isinstance(item, dict):
            continue
        file_id = _int_or_none(item.get("file_id"))
        if file_id is None:
            continue
        tracks.append({
            "id": _id(item.get("id")),
            "file_id": file_id,
            "role": item.get("role") if item.get("role") in TRACK_ROLES else "music",
            "volume": _num(item.get("volume"), 1.0, 0.0, 4.0),
            "delay": _num(item.get("delay"), 0.0, 0.0, 24 * 3600.0),
            "fade_in": _num(item.get("fade_in"), 0.0, 0.0, 30.0),
            "fade_out": _num(item.get("fade_out"), 0.0, 0.0, 30.0),
            "duck": _bool(item.get("duck"), False),
        })
        if len(tracks) >= MAX_TRACKS:
            break
    # only one voice track can push the others down (render `mix` rule)
    voices = [t for t in tracks if t["role"] == "voice"]
    for extra in voices[1:]:
        extra["role"] = "sfx"
    return {
        "keep_original": _bool(raw.get("keep_original"), True),
        "original_volume": _num(raw.get("original_volume"), 1.0, 0.0, 4.0),
        "tracks": tracks,
    }


# ── time arithmetic ─────────────────────────────────────────────────────────

def _dedupe(points: list[float], gap: float) -> list[float]:
    out: list[float] = []
    for p in sorted(points):
        if not out or p - out[-1] >= gap:
            out.append(p)
    return out


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    clean = sorted((min(a, b), max(a, b)) for a, b in ranges if abs(b - a) >= 0.01)
    out: list[list[float]] = []
    for a, b in clean:
        if out and a <= out[-1][1] + 0.001:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def segments(state: dict, duration: float) -> list[tuple[float, float]]:
    """Kept stretches of the source, in order: trim minus removed ranges."""
    start = float(state["trim"]["start"])
    end = state["trim"]["end"]
    end = float(duration) if end is None else min(float(end), float(duration))
    pieces = [(start, end)] if end - start > 0 else []
    for ra, rb in state.get("removed") or []:
        nxt: list[tuple[float, float]] = []
        for a, b in pieces:
            if rb <= a or ra >= b:
                nxt.append((a, b))
                continue
            if ra > a:
                nxt.append((a, ra))
            if rb < b:
                nxt.append((rb, b))
        pieces = nxt
    return [(round(a, 3), round(b, 3)) for a, b in pieces if b - a >= MIN_SEGMENT_S]


def output_duration(segs: list[tuple[float, float]]) -> float:
    return round(sum(b - a for a, b in segs), 3)


def to_output(t: float, segs: list[tuple[float, float]]) -> float | None:
    """Source time -> output time; ``None`` when that moment is cut out."""
    offset = 0.0
    for a, b in segs:
        if a <= t <= b:
            return round(offset + (t - a), 3)
        offset += b - a
    return None


def map_range(start: float, end: float, segs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A source range -> the output ranges where it is still visible. Pieces that
    touch in the output (the removed part between them is gone) are joined, so
    only a layer that starts or ends inside a removed piece can split."""
    out: list[tuple[float, float]] = []
    offset = 0.0
    for a, b in segs:
        lo, hi = max(a, start), min(b, end)
        if hi - lo > 0.001:
            piece = (round(offset + lo - a, 3), round(offset + hi - a, 3))
            if out and abs(out[-1][1] - piece[0]) <= 0.001:
                out[-1] = (out[-1][0], piece[1])
            else:
                out.append(piece)
        offset += b - a
    return out


def map_words(words: list[dict], segs: list[tuple[float, float]]) -> list[dict]:
    """Words whose start is still in the output, moved to output time; the end is
    clipped at the end of the kept piece the word starts in."""
    out: list[dict] = []
    offset = 0.0
    bounds = []
    for a, b in segs:
        bounds.append((a, b, offset))
        offset += b - a
    for w in words:
        for a, b, off in bounds:
            if a <= w["start"] < b:
                out.append({"text": w["text"], "start": round(off + w["start"] - a, 3),
                            "end": round(off + min(w["end"], b) - a, 3)})
                break
    return out


def part_points(state: dict, segs: list[tuple[float, float]]) -> list[float]:
    """Split marks moved to output time, for an export "in parts"."""
    total = output_duration(segs)
    points = []
    for c in state.get("cuts") or []:
        t = to_output(c, segs)
        if t is not None and MIN_SEGMENT_S < t < total - MIN_SEGMENT_S:
            points.append(t)
    return _dedupe(points, MIN_SEGMENT_S)[:MAX_CUTS]


def even(value: float) -> int:
    n = max(2, int(round(value)))
    return n if n % 2 == 0 else n - 1


def output_size(state: dict, source: dict, *, preview: bool = False, preview_max: int = 960) -> tuple[int, int]:
    """Frame of the result: the chosen aspect's render size, or the source size."""
    aspect = state["crop"]["aspect"]
    if aspect:
        w, h = ASPECT_SIZES[aspect]
    else:
        w = int(source.get("width") or 0) or 1920
        h = int(source.get("height") or 0) or 1080
    if preview and max(w, h) > preview_max:
        scale = preview_max / max(w, h)
        w, h = w * scale, h * scale
    return max(16, even(w)), max(16, even(h))


def referenced_files(state: dict) -> dict[str, list[int]]:
    """File ids the edits point at, by role (for checks and the usage list)."""
    return {
        "images": [layer["file_id"] for layer in state["layers"] if layer["type"] == "image"],
        "fonts": [layer["font_file_id"] for layer in state["layers"]
                  if layer["type"] == "text" and layer.get("font_file_id")],
        "tracks": [t["file_id"] for t in state["audio"]["tracks"]],
    }
