"""Module 12: subtitles and layers drawn into the frame (ASS text and picture overlays)."""

import io

from PIL import Image

from vf.core import files
from vf.modules.clip import overlays
from vf.modules.clip import state as st
from vf.modules.clip import subtitles as subs

WORDS = [
    {"text": "Hello", "start": 0.5, "end": 0.9},
    {"text": "world.", "start": 1.0, "end": 1.4},
    {"text": "Next", "start": 3.0, "end": 3.3},
    {"text": "{line}", "start": 3.4, "end": 3.8},
]


def png(size=(200, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


def test_presets_seeded(database):
    codes = [p["code"] for p in subs.list_presets()]
    assert codes == ["clean", "boxed", "pop", "brand"]
    assert subs.get_preset("nope")["code"] == "clean"
    assert subs.get_preset("pop")["mode"] == "word"


def test_timestamps_and_escape():
    assert subs.ts(0) == "0:00:00.00"
    assert subs.ts(3725.456) == "1:02:05.46"
    assert subs.escape("a{b}\\c\nd") == "a(b)∖c\\Nd"


def test_line_mode_lights_the_spoken_word(database):
    preset = subs.get_preset("clean")
    ass = subs.build_ass(WORDS, preset, width=1080, height=1920)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    lines = [x for x in ass.splitlines() if x.startswith("Dialogue:")]
    # "world." ends a sentence, so "Next" starts a new line
    assert len(lines) == 4
    assert lines[0].startswith("Dialogue: 0,0:00:00.50,0:00:01.00,Sub,")
    assert "\\c&H" in lines[0] and "Hello" in lines[0] and "world." in lines[0]
    assert "(line)" in lines[3]  # braces cannot open an override block


def test_word_mode_and_end_cut(database):
    preset = subs.get_preset("pop")
    ass = subs.build_ass(WORDS, preset, width=1080, height=1920, end_at=3.5)
    lines = [x for x in ass.splitlines() if x.startswith("Dialogue:")]
    assert len(lines) == 4
    assert "HELLO" in lines[0]  # pop is upper case
    assert lines[-1].split(",")[2] == "0:00:03.50"  # nothing after the end of the clip


def test_nothing_to_draw():
    assert subs.build_ass([], subs.FALLBACK_PRESET, width=100, height=100) == ""


def test_brand_folds_into_brand_preset(database):
    preset = subs.get_preset("brand")
    brand = {"colors": [{"hex": "#FF5500"}, {"hex": "#101010"}],
             "fonts": [{"family": "Brandy", "file_id": 9, "category": "display"}]}
    merged, fonts = subs.resolve_brand(preset, brand)
    assert merged["font_family"] == "Brandy" and fonts == [9]
    assert merged["highlight_color"] == "#FF5500" and merged["outline_color"] == "#101010"
    plain, none = subs.resolve_brand(subs.get_preset("clean"), brand)
    assert none == [] and plain["font_family"] != "Brandy"


def test_position_override(database):
    preset = subs.apply_position(subs.get_preset("clean"), "top")
    assert preset["alignment"] == 8
    assert subs.apply_position(preset, "")["alignment"] == 8


def test_burn_maps_layers_to_output_time(database):
    logo = files.save_bytes(png(), mime="image/png", name="logo.png")
    state = st.normalize({
        "removed": [[2, 4]],
        "subtitles": {"enabled": True, "words": WORDS},
        "layers": [
            {"type": "text", "text": "Title", "start": 1, "end": 5, "x": 0.5, "y": 0.1},
            {"type": "text", "text": "   ", "start": 0},
            {"type": "image", "file_id": logo["id"], "start": 0, "x": 0.9, "y": 0.9, "width": 0.1},
            {"type": "image", "file_id": logo["id"], "start": 1, "end": 5},
            {"type": "image", "file_id": 999999},
        ],
    }, 10)
    segs = st.segments(state, 10)
    assert segs == [(0.0, 2.0), (4.0, 10.0)]
    burn = overlays.build_burn(state, segs, width=1000, height=500, brand=None)
    ass = burn["ass"]
    assert "Style: Sub," in ass and "Style: T1," in ass
    titles = [x for x in ass.splitlines() if x.startswith("Dialogue: 1,")]
    # the title spans the removed piece 2-4 s: 1-5 s of the source is 1-3 s of the output
    assert [x.split(",")[1:3] for x in titles] == [["0:00:01.00", "0:00:03.00"]]
    assert "\\pos(500,50)" in titles[0]
    whole, part = burn["overlays"]
    assert whole == {"image": logo["path"], "x": 850, "y": 425, "width": 100, "opacity": 1.0}
    assert (part["start"], part["end"]) == (1.0, 3.0)
    assert burn["warnings"] == ["image_skipped"]
    assert burn["fonts"] == []


def test_burn_empty():
    state = st.normalize({}, 10)
    burn = overlays.build_burn(state, st.segments(state, 10), width=100, height=100, brand=None)
    assert burn == {"ass": "", "overlays": [], "fonts": [], "warnings": []}
