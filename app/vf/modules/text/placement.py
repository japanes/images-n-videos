"""Where the words go on the picture: «Place the text».

Ported from factory ``services/slide_text_placement.py``. Every block of words gets a
box, in this order (strongest evidence first):

1. ``layer``    — a text layer of the editor already shows this block: it stays as it is
   (unless «Place again» is on, then such layers are dropped and placed anew);
2. ``zone``     — the picture came from a style with a text map (``text_zones``) or the
   frame has its own map: the words go into the holes the design left for them,
   with a readable colour checked against the picture under the zone — no paid call;
3. ``vision``   — only when the person switched it on: one paid Gemini call (role
   ``text_placement``) with the picture shrunk to 512 px, for the blocks still without a place;
4. ``fallback`` — a column in the free space at the bottom (always works, free).

So the words always land somewhere, even with no model at all.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

from PIL import Image, ImageColor, ImageStat

from vf.core import google, prompts
from vf.core.errors import AppError
from vf.modules import library
from vf.modules.text import common as C
from vf.modules.text import layers as L

SOURCES = ("layer", "zone", "vision", "fallback")
TEMPERATURE = 0.2

# ── zones (a style's text map) ──────────────────────────────────────────────

_ZONE_ROLE_TO_BLOCK = {
    "headline": "headline", "subheadline": "headline",
    "body": "body", "annotation": "body", "benefit": "body", "footnote": "body", "other": "body",
    "eyebrow": "accent", "cta": "accent", "discount": "accent", "current_price": "accent",
    "old_price": "accent", "product_label": "accent", "logo": "accent",
}
_ZONE_ALIGN = {"left": "left", "center": "center", "centre": "center", "right": "right",
               "justify": "left", "start": "left", "end": "right"}
_ZONE_VERTICAL = {"top": "top", "center": "middle", "centre": "middle", "middle": "middle", "bottom": "bottom"}
# Colour words a designer writes in a zone map beyond what PIL knows ("deep navy" is not CSS navy).
_ZONE_COLOR_WORDS = {
    "off-white": "#F7F4EF", "offwhite": "#F7F4EF", "cream": "#F3EADF", "charcoal": "#2B2B2B",
    "graphite": "#3A3A3A", "navy": "#1B2A4A", "burgundy": "#6D1F2E", "terracotta": "#C36A4B",
    "sand": "#DFCDB4", "taupe": "#8C7B6B", "mint": "#B7E4C7", "peach": "#F6C3A6", "blush": "#F2D3D1",
    "mustard": "#D8A31A", "emerald": "#1F7A4C", "grey": "#808080", "gray": "#808080",
}
_ZONE_COLOR_MODIFIERS = {
    "very", "deep", "dark", "darker", "light", "lighter", "pale", "bright", "soft", "muted", "rich", "warm",
    "cool", "vivid", "pastel", "matte", "metallic", "neon", "solid", "semi", "transparent", "translucent",
    "opaque", "barely", "visible", "outline", "colour", "color", "tone", "shade", "tint",
}
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_WORD_RE = re.compile(r"[a-zA-Z-]+")
# Below this contrast display type on a photo disappears; the colour is overruled.
MIN_CONTRAST = 2.6
# A region this uneven (per-channel spread, 0..255) is a photo, not a plate: it needs a scrim.
BUSY_STDDEV = 46.0
MAX_ZONES = 6


def _clampf(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return max(low, min(high, number))


def zone_hex(value: Any) -> str | None:
    """A zone's colour words as ``#RRGGBB``, or None when they name nothing."""
    text = str(value or "").strip()
    if not text:
        return None
    if "{{" in text:   # "{{accent_color|bright lime green (#C7F53F)}}": only the fallback half is a colour
        text = text.replace("{{", " ").replace("}}", " ")
        if "|" in text:
            text = text.split("|", 1)[1]
    hit = _HEX_RE.search(text)
    if hit:
        return C.hex_color(hit.group(0))
    words = [w.lower() for w in _WORD_RE.findall(text)]
    words = [w for w in words if w not in _ZONE_COLOR_MODIFIERS]
    for start in range(len(words)):
        for candidate in (" ".join(words[start:]), "".join(words[start:]), words[start]):
            if candidate in _ZONE_COLOR_WORDS:
                return _ZONE_COLOR_WORDS[candidate]
            try:
                rgb = ImageColor.getrgb(candidate)
            except ValueError:
                continue
            return "#{:02X}{:02X}{:02X}".format(*rgb[:3])
    return None


def luminance(rgb: tuple[float, ...]) -> float:
    """Relative luminance, WCAG definition."""
    channels = []
    for c in rgb[:3]:
        s = c / 255.0
        channels.append(s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def region_stats(img: Image.Image | None, box: dict) -> tuple[tuple[float, float, float], float] | None:
    """Average colour and busyness of the picture under a box (fractions)."""
    if img is None:
        return None
    x0, y0 = max(0, int(box["x"] * img.width)), max(0, int(box["y"] * img.height))
    x1 = min(img.width, int((box["x"] + box["w"]) * img.width))
    y1 = min(img.height, int((box["y"] + box["h"]) * img.height))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    stat = ImageStat.Stat(img.convert("RGB").crop((x0, y0, x1, y1)))
    return (stat.mean[0], stat.mean[1], stat.mean[2]), sum(stat.stddev[:3]) / 3.0


def readable_color(img: Image.Image | None, box: dict) -> str:
    """White on a dark region, near-black on a light one."""
    stats = region_stats(img, box)
    if stats is None:
        return "#FFFFFF"
    return "#FFFFFF" if luminance(stats[0]) < 0.42 else "#111111"


def zones_of(raw: Any) -> list[dict]:
    """The zones of a text map, the ones that carry the message first, read top to bottom."""
    if not isinstance(raw, dict) or not isinstance(raw.get("zones"), list):
        return []
    zones = [z for z in raw["zones"] if isinstance(z, dict) and isinstance(z.get("box"), dict)]
    ranked = sorted(enumerate(zones), key=lambda p: (_clampf(p[1].get("priority"), -1e9, 1e9, 2.0 ** 53), p[0]))
    kept = ranked[:MAX_ZONES]
    rest = ranked[MAX_ZONES:]
    kept.sort(key=lambda p: (_clampf((p[1].get("box") or {}).get("y"), -1e9, 1e9, 2.0 ** 53), p[0]))
    return [z for _, z in kept] + [z for _, z in rest]


def match_zones(texts: list[dict], zones: list[dict]) -> list[dict | None]:
    """A zone for every block: by the zone id, then a zone for that kind of words, then reading order."""
    out: list[dict | None] = [None] * len(texts)
    taken: set[int] = set()
    by_id = {}
    for i, zone in enumerate(zones):
        zid = str(zone.get("id") or "").strip()
        if zid and zid not in by_id:
            by_id[zid] = i
    for bi, block in enumerate(texts):
        zi = by_id.get(str(block.get("zone_id") or "").strip())
        if zi is not None and zi not in taken:
            out[bi] = zones[zi]
            taken.add(zi)
    for bi, block in enumerate(texts):
        if out[bi] is not None:
            continue
        for zi, zone in enumerate(zones):
            if zi not in taken and _ZONE_ROLE_TO_BLOCK.get(str(zone.get("role") or "").lower(), "body") == block["role"]:
                out[bi] = zone
                taken.add(zi)
                break
    free = [i for i in range(len(zones)) if i not in taken]
    for bi in range(len(texts)):
        if out[bi] is None and free:
            zi = free.pop(0)
            out[bi] = zones[zi]
            taken.add(zi)
    return out


def zone_placement(zone: dict, img: Image.Image | None) -> dict:
    """One zone (box in percent of the canvas) as a placement in fractions."""
    raw = zone.get("box") or {}
    x = _clampf(raw.get("x"), 0.0, 100.0, 6.0) / 100.0
    y = _clampf(raw.get("y"), 0.0, 100.0, 40.0) / 100.0
    w = min(_clampf(raw.get("width", raw.get("w")), 1.0, 100.0, 88.0) / 100.0, 1.0 - x)
    h = min(_clampf(raw.get("height", raw.get("h")), 1.0, 100.0, 10.0) / 100.0, 1.0 - y)
    box = {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}
    typo = zone.get("typography") if isinstance(zone.get("typography"), dict) else {}
    color = zone_hex(typo.get("color"))
    scrim = False
    stats = region_stats(img, box)
    if stats is not None:
        mean, spread = stats
        auto = "#FFFFFF" if luminance(mean) < 0.42 else "#111111"
        if color is None:
            color = auto
        elif contrast(C.rgb(color), mean) < MIN_CONTRAST:
            # the words matter more than the swatch; a scrim only when the region is also busy
            C.log.info("text: zone %s colour %s unreadable on its region, using %s", zone.get("id"), color, auto)
            color = auto
            scrim = spread > BUSY_STDDEV
    elif color is None:
        color = "#FFFFFF"
    # the box is the type size: a single line filling the box, the renderer shrinks it to fit
    font_size = max(0.012, min(h / 1.28, 0.22))
    case = str(typo.get("case") or "").strip().lower()
    return {"box": box, "align": _ZONE_ALIGN.get(str(zone.get("alignment") or "").lower(), "center"),
            "vertical": _ZONE_VERTICAL.get(str(zone.get("vertical_alignment") or "").lower(), "middle"),
            "text_color": color, "needs_scrim": scrim, "font_size": round(font_size, 4),
            "uppercase": case in ("uppercase", "upper", "caps", "all-caps", "allcaps")}


# ── the vision call ─────────────────────────────────────────────────────────

def normalize(raw: Any) -> dict:
    """The model's box for one block, clamped into the frame."""
    raw = raw if isinstance(raw, dict) else {}
    box = raw.get("box") if isinstance(raw.get("box"), dict) else {}
    x = _clampf(box.get("x"), 0.0, 0.95, 0.06)
    y = _clampf(box.get("y"), 0.0, 0.95, 0.66)
    w = min(_clampf(box.get("w"), 0.2, 1.0, 0.88), 1.0 - x)
    h = min(_clampf(box.get("h"), 0.08, 1.0, 0.28), 1.0 - y)
    align = str(raw.get("align") or "center").lower()
    vertical = str(raw.get("vertical") or "bottom").lower()
    scrim = raw.get("needs_scrim", True)
    return {"box": {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)},
            "align": align if align in C.ALIGNS else "center",
            "vertical": vertical if vertical in C.VERTICALS else "bottom",
            "text_color": C.hex_color(raw.get("text_color"), "#FFFFFF"),
            "needs_scrim": scrim if isinstance(scrim, bool) else True}


def answer_json(result: Any) -> dict:
    """The JSON of an answer; a text answer is read from its first ``{`` to its last ``}``."""
    data = result.json
    text = result.text or ""
    if data is None and "{" in text:
        try:
            data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except ValueError:
            data = None
    return data if isinstance(data, dict) else {}


def thumbnail(img: Image.Image) -> google.Blob:
    """The picture as the vision model sees it: at most 512 px, JPEG."""
    small = img.convert("RGB")
    small.thumbnail((C.PLACEMENT_SIDE, C.PLACEMENT_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=80)
    return google.Blob(buf.getvalue(), "image/jpeg")


def _rects(boxes: list[dict]) -> str:
    return "; ".join(f"x={b['x']:.3f} y={b['y']:.3f} w={b['w']:.3f} h={b['h']:.3f}" for b in boxes)


def vision_request(texts: list[dict], avoid: list[dict], *, first: bool) -> tuple[str, str]:
    """``(system, request)`` of the placement call, built from the library's layers."""
    listing = "\n".join(f"{i}. role={t['role']}, size={t['size']}, text={t['text']!r}"
                        for i, t in enumerate(texts))
    if avoid:
        listing += "\n\n" + library.render_layer("SLIDE_TEXT_PLACEMENT_MULTI_AVOID", {"rects": _rects(avoid)}).strip()
    request = library.render_layer("SLIDE_TEXT_PLACEMENT_MULTI",
                                   {"cover": "cover" if first else "in-story", "listing": listing}).strip()
    system = library.render_layer("SLIDE_TEXT_PLACEMENT_MULTI_SYSTEM").strip()
    return system, request


def preview(texts: list[dict], avoid: list[dict], *, first: bool) -> dict:
    system, request = vision_request(texts, avoid, first=first)
    return {"system": system, "text": prompts.render(C.PROMPT_PLACEMENT, request=request).text}


async def ask_vision(img: Image.Image, texts: list[dict], avoid: list[dict], *, first: bool,
                     refs: list[tuple[str, int]], cancel=None) -> tuple[list[dict], Any]:
    """One paid call for all the blocks. Raises ``GoogleCallError`` (the gateway journaled it)."""
    system, request = vision_request(texts, avoid, first=first)
    result = await prompts.run_prompt(C.PROMPT_PLACEMENT, {"request": request}, purpose=C.PURPOSE_PLACEMENT,
                                      images=[thumbnail(img)], system=system, refs=refs, cancel=cancel,
                                      temperature=TEMPERATURE)
    data = answer_json(result)
    raw = data.get("blocks")
    if not isinstance(raw, list) or not raw:
        raise AppError("placement_empty", 502, "The model returned no boxes")
    return [normalize(raw[i]) if i < len(raw) else None for i in range(len(texts))], result


# ── the fallback ────────────────────────────────────────────────────────────

def stacked(texts: list[dict]) -> list[dict]:
    """A column at the bottom, one band per block (headlines get more room). Never overlaps."""
    n = len(texts)
    if not n:
        return []
    heights = [max(C.SIZE_RATIOS.get(t["size"], 0.045) * 2.4, 0.10) for t in texts]
    gap = 0.03
    total = sum(heights) + gap * (n - 1)
    if total > 0.88:
        scale = 0.88 / total
        heights = [h * scale for h in heights]
        gap *= scale
        total = 0.88
    y = max(0.06, 0.94 - total)
    out = []
    for h in heights:
        out.append({"box": {"x": 0.08, "y": round(y, 4), "w": 0.84, "h": round(h, 4)}, "align": "center",
                    "vertical": "middle", "text_color": "#FFFFFF", "needs_scrim": True})
        y += h + gap
    return out


def free_band(texts: list[dict], occupied: list[dict]) -> list[dict]:
    """Blocks with no place of their own, in the largest strip the placed ones leave free."""
    if not texts:
        return []
    spans = sorted([b["y"], min(1.0, b["y"] + b["h"])] for b in occupied if b["h"] > 0)
    merged: list[list[float]] = []
    for y0, y1 in spans:
        if merged and y0 <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])
    gaps = []
    cursor = 0.04
    for y0, y1 in merged:
        if y0 - cursor > 0.02:
            gaps.append((cursor, y0))
        cursor = max(cursor, y1)
    if 0.96 - cursor > 0.02:
        gaps.append((cursor, 0.96))
    top, bottom = max(gaps, key=lambda g: g[1] - g[0]) if gaps else (0.04, 0.96)
    n = len(texts)
    gap = 0.02 if n > 1 else 0.0
    band = max(0.03, ((bottom - top) - gap * (n - 1)) / n)
    band = min(band, 0.3)   # one short line does not need half the picture
    out = []
    y = bottom - band * n - gap * (n - 1) if bottom >= 0.9 else top   # the bottom strip is filled from below
    y = max(top, y)
    for _ in texts:
        out.append({"box": {"x": 0.06, "y": round(min(y, max(0.0, 0.98 - band)), 4), "w": 0.88,
                            "h": round(band, 4)},
                    "align": "center", "vertical": "middle", "text_color": "#FFFFFF", "needs_scrim": True})
        y += band + gap
    return out


def fallback(texts: list[dict], occupied: list[dict]) -> list[dict]:
    return free_band(texts, occupied) if occupied else stacked(texts)


# ── all together ────────────────────────────────────────────────────────────

def _layer_for(text: dict, placed: dict, layer_id: str, font: dict | None) -> dict:
    return L.text_layer({
        "type": "text", "block_id": text["id"], "role": text["role"], "text": text["text"], "size": text["size"],
        "font": font, "font_size": placed.get("font_size"), "color": placed["text_color"],
        "align": placed["align"], "vertical": placed["vertical"], "scrim": placed["needs_scrim"],
        "uppercase": placed.get("uppercase", False), **placed["box"],
    }, layer_id)


def _next_id(taken: set[str]) -> str:
    n = 1
    while f"p{n}" in taken:
        n += 1
    taken.add(f"p{n}")
    return f"p{n}"


async def place(texts: list[dict], current: list[dict], img: Image.Image, *, zones: Any = None,
                vision: bool = False, replace: bool = False, first: bool = True, font: dict | None = None,
                refs: list[tuple[str, int]] = (), cancel=None) -> dict:
    """``{layers, sources: {text_id: source}, error, model_id, cost_usd}``.

    ``current`` are the editor's layers; logos, shapes and free text layers always stay.
    A failed vision call does not stop anything: those blocks go to the fallback and
    ``error`` carries Google's words for the panel."""
    wanted = [t for t in texts if t["text"]]
    kept = [layer for layer in current
            if not (replace and layer["type"] == "text" and layer.get("block_id"))]
    sources: dict[str, str] = {}
    bound = {layer["block_id"] for layer in kept if layer["type"] == "text" and layer.get("block_id")}
    for t in wanted:
        if t["id"] in bound:
            sources[t["id"]] = "layer"
    occupied = [{k: layer[k] for k in ("x", "y", "w", "h")}
                for layer in kept if layer["type"] == "text" and layer.get("visible", True)]
    taken_ids = {layer["id"] for layer in kept}
    new_layers: list[dict] = []

    rest = [t for t in wanted if t["id"] not in sources]
    zone_list = zones_of(zones)
    if rest and zone_list:
        free_zones = [z for z in zone_list
                      if not any(overlap(zone_placement(z, None)["box"], b) > 0.5 for b in occupied)]
        for text, zone in zip(rest, match_zones(rest, free_zones), strict=True):
            if zone is None:
                continue
            placed = zone_placement(zone, img)
            new_layers.append(_layer_for(text, placed, _next_id(taken_ids), font))
            occupied.append(placed["box"])
            sources[text["id"]] = "zone"

    error = None
    model_id = None
    cost = 0.0
    rest = [t for t in wanted if t["id"] not in sources]
    if rest and vision:
        try:
            boxes, result = await ask_vision(img, rest, occupied, first=first, refs=list(refs), cancel=cancel)
            model_id, cost = result.model_id, result.cost_usd
            for text, placed in zip(rest, boxes, strict=True):
                if placed is None:
                    continue
                new_layers.append(_layer_for(text, placed, _next_id(taken_ids), font))
                sources[text["id"]] = "vision"
            occupied.extend(layer_box(layer) for layer in new_layers if sources.get(layer["block_id"]) == "vision")
        except google.GoogleCallError as exc:
            error = {"code": exc.code, "message": exc.raw or exc.message}
        except AppError as exc:
            error = {"code": exc.code, "message": exc.message}

    rest = [t for t in wanted if t["id"] not in sources]
    for text, placed in zip(rest, fallback(rest, occupied), strict=True):
        new_layers.append(_layer_for(text, placed, _next_id(taken_ids), font))
        sources[text["id"]] = "fallback"
    return {"layers": [*kept, *new_layers], "sources": sources, "error": error, "model_id": model_id,
            "cost_usd": cost}


def layer_box(layer: dict) -> dict:
    return {k: layer[k] for k in ("x", "y", "w", "h")}


def overlap(a: dict, b: dict) -> float:
    """Share of box ``a`` that box ``b`` covers, 0..1."""
    area = a["w"] * a["h"]
    if area <= 0:
        return 0.0
    dx = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    dy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return dx * dy / area


__all__ = ["SOURCES", "answer_json", "fallback", "match_zones", "normalize", "place", "preview", "readable_color",
           "stacked", "zone_hex", "zone_placement", "zones_of"]
