"""Stand-in answers for working without a Google key (``VF_GOOGLE_MODE=stub``).

The stub goes through the same journal, limiter and retry path as a real
call; only the network request is replaced. Rows are marked ``stub = 1`` and
priced as usual, so the spend screens show realistic numbers.

Test hooks in the prompt text (stub mode only):
``[stub:error=<code>]`` fails the call, ``[stub:blocked]`` returns a safety
block, ``[stub:refused]`` returns an answer without a picture.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Output pixel sizes of the image models at the "1K" tier, by aspect ratio.
SIZES_1K = {
    "1:1": (1024, 1024), "2:3": (832, 1248), "3:2": (1248, 832), "3:4": (896, 1200), "4:3": (1200, 896),
    "4:5": (928, 1152), "5:4": (1152, 928), "9:16": (768, 1376), "16:9": (1376, 768), "21:9": (1584, 672),
}
TIER_SCALE = {"512": 0.5, "1K": 1.0, "2K": 2.0, "4K": 4.0}


class StubFailure(Exception):
    def __init__(self, code: str):
        super().__init__(f"stub failure: {code}")
        self.code = code


@dataclass
class StubAnswer:
    text: str = ""
    images: list[tuple[bytes, str]] = field(default_factory=list)
    blocked: bool = False
    refusal: str = ""
    finish_reason: str = "STOP"
    queries: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


def delay() -> float:
    try:
        return float(os.environ.get("VF_STUB_DELAY", "0.4"))
    except ValueError:
        return 0.4


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def image(prompt: str, aspect_ratio: str | None, image_size: str | None, index: int = 0) -> tuple[bytes, str]:
    w, h = SIZES_1K.get(aspect_ratio or "1:1", SIZES_1K["1:1"])
    scale = min(TIER_SCALE.get(image_size or "1K", 1.0), 1.0)  # keep stub files small
    w, h = int(w * scale), int(h * scale)
    seed = _seed(f"{prompt}|{index}")
    top = ((seed >> 16) & 0xFF, (seed >> 8) & 0xFF, seed & 0xFF)
    bottom = tuple(255 - c for c in top)
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    for y in range(0, h, 4):
        t = y / max(h - 1, 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        draw.rectangle([0, y, w, y + 4], fill=color)
    font = ImageFont.load_default(size=max(18, w // 18))
    small = ImageFont.load_default(size=max(12, w // 40))
    draw.rectangle([0, 0, w, h // 6], fill=(0, 0, 0))
    draw.text((w // 20, h // 40), f"STUB #{index + 1}  {aspect_ratio or '1:1'}", fill=(255, 255, 255), font=font)
    words = re.sub(r"\s+", " ", prompt).strip()[:240]
    lines, line = [], ""
    for word in words.split(" "):
        if len(line) + len(word) > 34:
            lines.append(line)
            line = ""
        line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    y = h // 4
    for text in lines[:8]:
        draw.text((w // 20, y), text, fill=(255, 255, 255), font=small, stroke_width=2, stroke_fill=(0, 0, 0))
        y += int(small.size * 1.4)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue(), "image/png"


def from_schema(schema: dict | None, prompt: str = "", path: str = "value") -> Any:
    """A small value that satisfies a JSON schema (enough for UI and tests)."""
    schema = schema or {}
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            options = [s for s in schema[key] if s.get("type") != "null"] or schema[key]
            return from_schema(options[0], prompt, path)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {name: from_schema(sub, prompt, name) for name, sub in props.items()}
    if kind == "array":
        items = schema.get("items") or {"type": "string"}
        count = max(int(schema.get("minItems") or 0), min(int(schema.get("maxItems") or 2), 2))
        if items.get("type") in ("number", "integer") and count >= 4 or "box" in path:
            values = [100, 150, 700, 850][: max(count, 4)]
            return values if items.get("type") == "integer" else [float(v) for v in values]
        return [from_schema(items, prompt, f"{path}_{i}") for i in range(count)]
    if kind == "integer":
        return int(schema.get("minimum") or 1)
    if kind == "number":
        lo = float(schema.get("minimum") or 0)
        hi = float(schema.get("maximum") or (lo + 1))
        return round((lo + hi) / 2, 3)
    if kind == "boolean":
        return True
    max_len = schema.get("maxLength")
    text = f"stub {path}"
    return text[: int(max_len)] if max_len else text


def text_for(prompt: str) -> str:
    head = re.sub(r"\s+", " ", prompt).strip()[:160]
    return f"[stub answer] {head}"


def _marker(prompt: str) -> str | None:
    m = re.search(r"\[stub:(error=([a-z_]+)|blocked|refused)\]", prompt)
    if not m:
        return None
    return m.group(2) or m.group(1)


async def answer(*, prompt: str, response: str, schema: dict | None = None, aspect_ratio: str | None = None,
                 image_size: str | None = None, search: bool = False, index: int = 0) -> StubAnswer:
    await asyncio.sleep(delay())
    marker = _marker(prompt)
    if marker == "blocked":
        return StubAnswer(blocked=True, refusal="finish_reason=SAFETY (stub)", finish_reason="SAFETY")
    if marker == "refused":
        return StubAnswer(text="I can't draw that (stub).", refusal="model said: I can't draw that (stub).")
    if marker:
        raise StubFailure(marker)
    out = StubAnswer()
    if search:
        out.queries = [prompt[:60] or "stub query"]
        out.sources = [{"title": "Example source (stub)", "url": "https://example.com/"}]
    if response == "image":
        out.images = [image(prompt, aspect_ratio, image_size, index)]
    elif response == "json":
        out.text = json.dumps(from_schema(schema, prompt), ensure_ascii=False)
    else:
        out.text = text_for(prompt)
    return out


def video_fixture(aspect_ratio: str | None) -> Path:
    """A short mp4 with sound, portrait or landscape."""
    name = "stub-16x9.mp4" if aspect_ratio in ("16:9", "4:3", "3:2", "21:9") else "stub-9x16.mp4"
    return FIXTURES / name


def usage(prompt: str, n_images_in: int, answer: StubAnswer, image_tokens: int = 1120) -> tuple[int, int, int]:
    """Plausible (tokens_in, tokens_out, tokens_thinking) so the stub costs something."""
    tokens_in = max(1, len(prompt) // 4) + n_images_in * 560
    if answer.blocked:
        return tokens_in, 0, 0
    tokens_out = len(answer.images) * image_tokens + max(0, len(answer.text) // 4)
    thinking = 0 if answer.images else 120
    return tokens_in, tokens_out + thinking, thinking
