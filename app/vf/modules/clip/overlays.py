"""What goes into render ``burn``: one ASS track (subtitles + text layers) and
the picture overlays (logos), all moved from source time to output time and
multiplied out against the frame being rendered.

Text is drawn by libass, not as pictures: one style per text layer, positioned
with ``\\pos`` at the layer's center. Text layers sit on ASS layer 1 and above,
subtitles on layer 0, so a title stays on top of the captions.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from vf.core import db
from vf.modules.clip import subtitles as subs
from vf.modules.clip.state import map_range, map_words, output_duration

MAX_OVERLAYS = 32           # render `burn` limit
MAX_FONTS = 32
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
FONT_EXTS = (".ttf", ".otf", ".ttc", ".woff", ".woff2")


def _file(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    return db.get("files", int(file_id))


def _ext(row: dict) -> str:
    return PurePosixPath(row.get("path") or "").suffix.lower()


def _text_style(name: str, layer: dict, height: int) -> str:
    """A style for one text layer: centered (\\an5), no margins."""
    size_ratio = float(layer.get("size") or 0.05)
    preset: dict[str, Any] = {
        "font_family": layer.get("font") or "DejaVu Sans",
        "font_size_ratio": size_ratio,
        "bold": layer.get("bold"), "italic": layer.get("italic"),
        "primary_color": layer.get("color") or "#FFFFFF",
        "alignment": 5, "margin_v_ratio": 0, "margin_h_ratio": 0, "shadow_ratio": 0,
    }
    if layer.get("plate"):
        # BorderStyle 3: the outline becomes a box around the text, filled with OutlineColour.
        preset.update(border_style=3, back_color=layer.get("plate_color") or "#000000",
                      back_opacity=float(layer.get("plate_opacity") if layer.get("plate_opacity") is not None
                                         else 0.6),
                      outline_ratio=0.25)
    else:
        preset.update(border_style=1, outline_color="#000000",
                      outline_ratio=0.08 if layer.get("outline") else 0.0)
    return subs.style_line(name, preset, 1, height)


def text_dialogues(layers: list[dict], segs: list[tuple[float, float]], width: int,
                   height: int) -> tuple[list[str], list[str]]:
    """(styles, dialogues) for the visible text layers."""
    styles: list[str] = []
    dialogues: list[str] = []
    total = output_duration(segs)
    n = 0
    for layer in layers:
        if layer.get("type") != "text" or not layer.get("visible", True):
            continue
        text = str(layer.get("text") or "").strip()
        if not text:
            continue
        end = layer.get("end")
        ranges = map_range(float(layer.get("start") or 0), float(end) if end is not None else 10 ** 9, segs)
        if not ranges:
            continue
        n += 1
        name = f"T{n}"
        styles.append(_text_style(name, layer, height))
        cx = int(round(float(layer.get("x", 0.5)) * width))
        cy = int(round(float(layer.get("y", 0.5)) * height))
        body = f"{{\\an5\\pos({cx},{cy})}}{subs.escape(text)}"
        for start, stop in ranges:
            stop = min(stop, total)
            if stop - start < subs.MIN_EVENT_S:
                continue
            dialogues.append(f"Dialogue: {n},{subs.ts(start)},{subs.ts(stop)},{name},,0,0,0,,{body}")
    return styles, dialogues


def image_overlays(layers: list[dict], segs: list[tuple[float, float]], width: int,
                   height: int) -> tuple[list[dict], list[str]]:
    """(overlays for render, warnings); times are output times, a layer over the whole clip has none."""
    out: list[dict] = []
    warnings: list[str] = []
    total = output_duration(segs)
    for layer in layers:
        if layer.get("type") != "image" or not layer.get("visible", True):
            continue
        row = _file(layer.get("file_id"))
        if row is None or row["kind"] != "image" or _ext(row) not in IMAGE_EXTS:
            warnings.append("image_skipped")
            continue
        w = max(2, int(round(float(layer.get("width") or 0.2) * width)))
        w -= w % 2
        iw, ih = row.get("width") or 0, row.get("height") or 0
        h = int(round(w * ih / iw)) if iw and ih else w
        x = int(round(float(layer.get("x", 0.5)) * width - w / 2))
        y = int(round(float(layer.get("y", 0.5)) * height - h / 2))
        end = layer.get("end")
        ranges = map_range(float(layer.get("start") or 0), float(end) if end is not None else 10 ** 9, segs)
        whole = len(ranges) == 1 and ranges[0][0] <= 0.001 and ranges[0][1] >= total - 0.001
        for start, stop in ranges:
            if len(out) >= MAX_OVERLAYS:
                warnings.append("too_many_overlays")
                break
            item: dict[str, Any] = {"image": row["path"], "x": x, "y": y, "width": w,
                                    "opacity": round(float(layer.get("opacity", 1.0)), 3)}
            if not whole:
                item.update(start=round(start, 3), end=round(min(stop, total), 3))
                if item["end"] <= item["start"]:
                    continue
            out.append(item)
    return out, warnings


def font_paths(file_ids: list[int]) -> list[str]:
    """Data-relative paths of font files that exist and look like fonts."""
    out: list[str] = []
    for fid in file_ids:
        row = _file(fid)
        if row is None or row["kind"] != "font" or _ext(row) not in FONT_EXTS:
            continue
        if row["path"] not in out:
            out.append(row["path"])
    return out[:MAX_FONTS]


def build_burn(state: dict, segs: list[tuple[float, float]], *, width: int, height: int,
               brand: dict | None) -> dict:
    """Everything for the ``burn`` step: ``{"ass", "overlays", "fonts", "warnings"}``.
    ``ass`` is "" and ``overlays`` empty when there is nothing to draw."""
    total = output_duration(segs)
    styles: list[str] = []
    dialogues: list[str] = []
    font_ids: list[int] = []

    sub = state.get("subtitles") or {}
    if sub.get("enabled") and sub.get("words"):
        preset = subs.get_preset(sub.get("preset_code"))
        preset, brand_fonts = subs.resolve_brand(preset, brand)
        preset = subs.apply_position(preset, sub.get("position"))
        font_ids.extend(brand_fonts)
        words = map_words(sub["words"], segs)
        sub_lines = subs.subtitle_dialogues(words, preset, mode=sub.get("mode"), end_at=total)
        if sub_lines:
            styles.append(subs.style_line("Sub", preset, width, height))
            dialogues.extend(sub_lines)

    text_styles, text_lines = text_dialogues(state.get("layers") or [], segs, width, height)
    styles.extend(text_styles)
    dialogues.extend(text_lines)
    font_ids.extend(layer["font_file_id"] for layer in state.get("layers") or []
                    if layer.get("type") == "text" and layer.get("font_file_id"))

    overlays, warnings = image_overlays(state.get("layers") or [], segs, width, height)
    return {
        "ass": subs.document(width, height, styles, dialogues),
        "overlays": overlays,
        "fonts": font_paths(font_ids) if dialogues else [],
        "warnings": warnings,
    }
