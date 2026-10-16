"""Module 06 (text on image): the Pillow renderer.

The brand font draws what it has; the bundled Roboto draws the rest, so a Latin-only brand
font never leaves boxes («tofu») in a Cyrillic line. Characters no font has are left out and
named in the report. Also: colours, the scrim, alignment, shapes, logos, hidden layers.
"""

import io
import re
from pathlib import Path

import pytest
from fontTools import subset
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image

from vf.core import files, prompts
from vf.modules.brand import kits
from vf.modules.text import fonts as F
from vf.modules.text import layers as L
from vf.modules.text import render as R

TEXT_DIR = Path(__file__).resolve().parents[1] / "vf" / "modules" / "text"


def png(color=(20, 20, 20), size=(400, 500)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def latin_roboto(family: str = "Latin Only") -> bytes:
    """The bundled Roboto cut down to ASCII: a brand font that has no Cyrillic at all."""
    font = TTFont(F.REGULAR)
    options = subset.Options()
    options.name_IDs = ["*"]
    sub = subset.Subsetter(options)
    sub.populate(unicodes=range(0x20, 0x7F))
    sub.subset(font)
    for record in font["name"].names:
        if record.nameID in (1, 4, 16):
            record.string = family
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def triangle_font(family: str = "Triangle") -> bytes:
    """A font with one glyph: «A» drawn as a triangle (nothing else, not even a space)."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 700))
    pen.lineTo((600, 0))
    pen.closePath()
    glyph = pen.glyph()
    fb.setupGlyf({".notdef": glyph, "A": glyph})
    fb.setupHorizontalMetrics({".notdef": (650, 0), "A": (650, 0)})
    fb.setupHorizontalHeader(ascent=900, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(usWeightClass=400)
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def kit_font(data: bytes, name: str) -> int:
    kit = kits.create_kit(f"Kit {name}")
    asset = kits.add_font_upload(kit["id"], data, filename=f"{name}.ttf")
    return asset["file_id"]


def text(words: str, font_file: int | None = None, **extra) -> dict:
    raw = {"type": "text", "id": "t", "role": "body", "text": words, "color": "#FFFFFF", "size": "xl",
           "x": 0.05, "y": 0.3, "w": 0.9, "h": 0.4, **extra}
    if font_file:
        raw["font"] = {"file_id": font_file, "family": "Brand"}
    return L.normalize_layers([raw])[0]


def bright(img: Image.Image, box=None, level=200) -> int:
    area = img.crop(box) if box else img
    return sum(1 for p in area.getdata() if min(p) >= level)


# ── no tofu ─────────────────────────────────────────────────────────────────


def test_cyrillic_with_a_latin_only_brand_font_is_drawn_by_roboto(database):
    font_file = kit_font(latin_roboto(), "latin")
    assert F.font_path(font_file) is not None
    assert ord("П") not in F.coverage(F.font_path(font_file)) and ord("H") in F.coverage(F.font_path(font_file))
    bg = png()
    with_brand, report = R.render(bg, [text("Привет", font_file)])
    plain, plain_report = R.render(bg, [text("Привет")])
    assert report["fallback_chars"] == "".join(sorted(set("Привет")))
    assert report["missing_chars"] == "" and report["missing_files"] == []
    assert plain_report["fallback_chars"] == ""  # no brand font: Roboto is the font, not a substitute
    # the brand font lacks every letter, so every pixel is Roboto's — no box, no gap
    assert image(with_brand).tobytes() == image(plain).tobytes()
    assert bright(image(with_brand)) > 200


def test_mixed_latin_and_cyrillic_line(database):
    font_file = kit_font(latin_roboto(), "latin")
    _, report = R.render(png(), [text("Sale -20% Распродажа", font_file)])
    assert report["fallback_chars"] == "".join(sorted(set("Распродажа")))
    assert report["missing_chars"] == ""
    _, latin = R.render(png(), [text("Sale -20% today", font_file)])
    assert latin["fallback_chars"] == "" and latin["missing_chars"] == ""


def test_brand_glyphs_are_the_brand_ones(database):
    font_file = kit_font(triangle_font(), "triangle")
    bg = png()
    brand, report = R.render(bg, [text("AБ", font_file)])
    roboto, _ = R.render(bg, [text("AБ")])
    assert report["fallback_chars"] == "Б" and report["missing_chars"] == ""
    assert image(brand).tobytes() != image(roboto).tobytes()


def test_characters_no_font_has_are_left_out_not_boxed(database):
    bg = png()
    drawn, report = R.render(bg, [text("漢字")])
    empty, _ = R.render(bg, [])
    assert report["missing_chars"] == "".join(sorted("漢字"))
    assert image(drawn).tobytes() == image(empty).tobytes()


def test_a_font_file_that_is_gone_falls_back_and_is_reported(database):
    gone = files.save_bytes(b"not a font", mime="text/plain", name="x.txt", origin="upload")
    drawn, report = R.render(png(), [text("Hello", gone["id"])])
    assert report["missing_files"] == ["t"]
    assert bright(image(drawn)) > 50


# ── colours, places, the plate ──────────────────────────────────────────────


def test_white_words_stay_inside_their_box():
    data, report = R.render(png(), [text("Hello world")])
    img = image(data)
    assert (report["width"], report["height"]) == (400, 500)
    box = (int(0.05 * 400), int(0.3 * 500), int(0.95 * 400), int(0.7 * 500))
    assert bright(img, box) > 100
    assert bright(img) == bright(img, box)


def test_colour_of_the_words():
    img = image(R.render(png((240, 240, 240)), [text("Hello", color="#FF0000")])[0])
    reds = sum(1 for r, g, b in img.getdata() if r > 200 and g < 60 and b < 60)
    assert reds > 50


@pytest.mark.parametrize(("vertical", "low", "high"), [("top", 0.0, 0.5), ("bottom", 0.5, 1.0)])
def test_vertical_alignment(vertical, low, high):
    img = image(R.render(png(), [text("Hi", vertical=vertical, x=0, y=0, w=1, h=1, size="md")])[0])
    rows = [y for y in range(img.height) if any(min(img.getpixel((x, y))) > 200 for x in range(0, img.width, 2))]
    middle = (rows[0] + rows[-1]) / 2 / img.height
    assert low <= middle <= high


@pytest.mark.parametrize(("align", "side"), [("left", "left"), ("right", "right")])
def test_horizontal_alignment(align, side):
    img = image(R.render(png(), [text("Hi", align=align, x=0, y=0, w=1, h=1, size="md")])[0])
    cols = [x for x in range(img.width) if any(min(img.getpixel((x, y))) > 200 for y in range(0, img.height, 2))]
    centre = (cols[0] + cols[-1]) / 2 / img.width
    assert centre < 0.4 if side == "left" else centre > 0.6


def test_scrim_darkens_under_light_words():
    bg = png((200, 200, 200))
    plain = image(R.render(bg, [text("Hi", size="md")])[0])
    plated = image(R.render(bg, [text("Hi", size="md", scrim=True)])[0])
    probe = (int(0.12 * 400), 250)  # inside the box, beside the words
    assert sum(plated.getpixel(probe)) < sum(plain.getpixel(probe)) - 30
    assert plated.getpixel((5, 5)) == plain.getpixel((5, 5))


def test_words_that_do_not_fit_are_reported():
    long = " ".join(["Word"] * 200)
    _, report = R.render(png(), [text(long, x=0.4, y=0.45, w=0.2, h=0.05)])
    assert report["clipped"] == ["t"]


def test_shapes_and_hidden_layers():
    layers = L.normalize_layers([
        {"type": "shape", "id": "r", "fill": "#FF0000", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5},
        {"type": "shape", "id": "e", "shape": "ellipse", "fill": "#00FF00", "x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5},
        {"type": "shape", "id": "h", "fill": "#0000FF", "x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5, "visible": False},
        {"type": "shape", "id": "o", "fill": "#FFFFFF", "x": 0.0, "y": 0.5, "w": 0.5, "h": 0.5, "opacity": 0.5},
    ])
    img = image(R.render(png((0, 0, 0)), layers)[0])
    assert img.getpixel((100, 125)) == (255, 0, 0)
    assert img.getpixel((300, 375)) == (0, 255, 0)
    assert img.getpixel((398, 252)) == (0, 0, 0)        # the ellipse leaves its corners free
    assert img.getpixel((300, 125)) == (0, 0, 0)        # hidden
    assert 110 < img.getpixel((100, 375))[0] < 145      # half white over black


def test_logo_layer_from_its_file_or_the_kit(database):
    logo = files.save_bytes(png((0, 200, 0), (40, 40)), mime="image/png", name="logo.png", origin="upload")
    own = L.normalize_layers([{"type": "logo", "id": "lg", "file_id": logo["id"], "x": 0.5, "y": 0.5,
                               "w": 0.2, "h": 0.2}])
    img = image(R.render(png((0, 0, 0)), own)[0])
    assert img.getpixel((240, 300)) == (0, 200, 0)
    kit_logo = L.normalize_layers([{"type": "logo", "id": "lg", "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}])
    img = image(R.render(png((0, 0, 0)), kit_logo, logo_file_id=logo["id"])[0])
    assert img.getpixel((240, 300)) == (0, 200, 0)
    _, report = R.render(png((0, 0, 0)), L.normalize_layers([{"type": "logo", "id": "gone", "file_id": 99999}]))
    assert report["missing_files"] == ["gone"]


def test_preview_size_and_a_broken_background():
    data, report = R.render(png(size=(800, 1000)), [text("Hi")], max_side=200)
    assert image(data).size == (160, 200) and (report["width"], report["height"]) == (160, 200)
    with pytest.raises(Exception) as caught:
        R.render(b"not a picture", [])
    assert getattr(caught.value, "code", None) == "bad_image"


# ── layers: checking and the words ──────────────────────────────────────────


def test_layers_are_checked():
    from vf.core.errors import AppError

    with pytest.raises(AppError) as e:
        L.normalize_layers([{"type": "video"}])
    assert e.value.code == "bad_layer"
    with pytest.raises(AppError) as e:
        L.normalize_layers([{"type": "shape"}] * 31)
    assert e.value.code == "too_many_layers"
    with pytest.raises(AppError) as e:
        L.normalize_texts([{"text": "a"}] * 9)
    assert e.value.code == "too_many_texts"
    layer = L.normalize_layers([{"type": "text", "id": "x", "x": 0.9, "w": 0.5, "color": "red", "align": "?"}])[0]
    assert layer["x"] + layer["w"] <= 1.0 and layer["color"] == "#FFFFFF" and layer["align"] == "center"
    twice = L.normalize_layers([{"type": "shape", "id": "a"}, {"type": "shape", "id": "a"}])
    assert len({x["id"] for x in twice}) == 2


def test_layers_follow_their_words():
    texts = L.normalize_texts([{"role": "headline", "text": "Big"}, {"role": "body", "text": "Small"}])
    layers = L.normalize_layers([{"type": "text", "block_id": texts[1]["id"], "text": "old"},
                                 {"type": "text", "block_id": "gone", "text": "free"}])
    bound = L.bind_texts(layers, texts)
    assert bound[0]["text"] == "Small" and bound[1]["block_id"] is None and bound[1]["text"] == "free"
    layout = [{"type": "text", "role": "body", "x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1},
              {"type": "text", "role": "headline", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.2},
              {"type": "text", "role": "accent"},
              {"type": "shape"}]
    filled = L.from_layout(layout, texts)
    assert [x["type"] for x in filled] == ["text", "text", "shape"]
    assert filled[0]["text"] == "Small" and filled[1]["text"] == "Big"


# ── prompt layers the module reads ──────────────────────────────────────────


def test_every_prompt_layer_the_module_uses_exists_and_fills():
    used: set[str] = set()
    for path in TEXT_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        used.update(re.findall(r"""_layer\(\s*["']([A-Z0-9_]+)["']""", source))
        used.update(re.findall(r"""render_layer\(\s*["']([A-Z0-9_]+)["']""", source))
        used.update(re.findall(r"""^LAYER_\w+\s*=\s*["']([A-Z0-9_]+)["']""", source, re.MULTILINE))
    assert len(used) >= 15
    known = set(prompts.load(force=True))
    assert sorted(used - known) == []
    from vf.modules.library import templates

    for code in sorted(used):
        needs = templates.layer_variables(code)
        values = {name: f"<{name}>" for name in needs["values"] + needs["conditions"]}
        values.update({name: ["a"] for name in needs["lists"]})
        out = templates.render_layer(code, values)
        assert out.strip() and "{{" not in out, code
