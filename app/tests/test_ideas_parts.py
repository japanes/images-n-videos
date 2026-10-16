"""Module 05 (shot ideas), the parts without Google: the setting and its dice,
the brief check, reading the model's answer, the screen names of the setting."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vf.core.errors import AppError
from vf.modules.ideas import brief as B
from vf.modules.ideas import common as C
from vf.modules.ideas import research as R
from vf.modules.ideas import scene
from vf.modules.ideas import write as WR

WEB = Path(__file__).resolve().parents[2] / "web"


# ── the setting ─────────────────────────────────────────────────────────────


def test_every_axis_and_item_is_complete():
    axes = scene.axes()
    assert [a["id"] for a in axes] == ["surface", "backdrop", "light", "camera", "atmosphere", "props",
                                       "palette", "state"]
    ids = [i["id"] for a in axes for i in a["items"]]
    assert len(ids) == len(set(ids)) and len(ids) > 150
    tags = {t for a in axes for i in a["items"] for t in i.get("tags") or []}
    for axis in axes:
        assert axis["name"] and axis["note"] and axis["roll"] in ("always", "sometimes")
        for item in axis["items"]:
            assert item["en"].strip() and isinstance(item.get("tags", []), list)
            assert set(item.get("avoid") or []) <= tags and set(item.get("requires") or []) <= tags


def test_the_dice_keep_the_setting_compatible():
    index = scene._index()
    seen_axes: set[str] = set()
    for seed in range(300):
        picked = scene.roll(seed)
        assert {"surface", "backdrop", "light", "camera"} <= set(picked)
        tags: set[str] = set()
        for axis in scene.axes():                      # the dice go axis by axis in this order
            for item_id in picked.get(axis["id"]) or []:
                item = index[item_id]
                assert not set(item.get("avoid") or []) & tags, (seed, item_id)
                needed = set(item.get("requires") or [])
                assert not needed or needed & tags, (seed, item_id)
                tags |= set(item.get("tags") or [])
        assert all(len(v) == 1 for v in picked.values())
        seen_axes |= set(picked)
    assert seen_axes == {a["id"] for a in scene.axes()}           # "sometimes" axes do come out
    assert scene.roll(5) == scene.roll(5)


def test_a_hand_pick_is_put_in_order_and_cut_to_the_axis_cap():
    props = [i["id"] for i in next(a for a in scene.axes() if a["id"] == "props")["items"]][:3]
    light = next(a for a in scene.axes() if a["id"] == "light")["items"][0]["id"]
    picked = scene.normalize({"x": props, "y": [light, light]})
    assert list(picked) == ["light", "props"] and picked["props"] == props[:2] and picked["light"] == [light]
    assert scene.normalize([light]) == {"light": [light]} and scene.normalize(None) == {}
    with pytest.raises(AppError) as unknown:
        scene.normalize({"light": ["moonlight_from_mars"]})
    assert unknown.value.code == "ideas_scene_unknown"


def test_the_setting_goes_to_the_model_word_for_word():
    index = scene._index()
    light = next(a for a in scene.axes() if a["id"] == "light")["items"][0]["id"]
    props = [i["id"] for i in next(a for a in scene.axes() if a["id"] == "props")["items"]][:2]
    text = scene.as_block({"props": props, "light": [light]})
    lines = text.splitlines()
    assert lines[0] == scene.BLOCK_HEADING
    assert lines[1] == f"LIGHT: {index[light]['en']}"
    assert lines[2] == f"PROPS: {index[props[0]]['en']}; {index[props[1]]['en']}"
    assert len(text) > len("\n".join(lines[:3])) + 20               # followed by the author's-choice rule
    assert scene.as_block({}) == ""


# ── the brief ───────────────────────────────────────────────────────────────


def test_the_brief_is_cleaned_and_checked(database):
    out = B.clean({"niche": "  Coffee \n beans ", "brand": "  Bean\n\n Co ", "count": "4", "language": "ru",
                   "unknown": "dropped"})
    assert out["niche"] == "Coffee beans" and out["brand"] == "Bean\nCo" and out["count"] == 4
    assert out["language"] == "ru" and "unknown" not in out and out["product_refs"] == []
    assert B.clean({"niche": "x"})["count"] == 0 and B.clean({"niche": "x"})["language"] == C.DEFAULT_LANGUAGE
    for bad, code in (({"niche": " "}, "ideas_niche_empty"), ({"niche": "x", "count": -1}, "ideas_bad_count"),
                      ({"niche": "x", "count": "many"}, "ideas_bad_count"),
                      ({"niche": "x", "language": "pl"}, "ideas_bad_language"),
                      ({"niche": "x", "product_refs": "1"}, "bad_request"), ("niche", "bad_request")):
        with pytest.raises(AppError) as refused:
            B.clean(bad)
        assert refused.value.code == code
    assert B.file_ids({"product_refs": [3, 1], "visual_refs": [1, 5]}) == [3, 1, 5]


def test_the_brief_text_names_the_language_and_the_pictures(database):
    brief = B.clean({"niche": "Tea", "language": "uk", "count": 2, "visual_note": "Calm, lots of air"})
    text = B.user_input(brief, product_count=0, visual_count=2)
    assert "Tea" in text and "Ukrainian" in text and "2 image(s) attached to this message" in text
    assert "Calm, lots of air" in text and text.endswith("LABEL_LANGUAGE: Ukrainian")
    assert "COUNT:\n2" in text and C.RESEARCH_HEADING not in text and scene.BLOCK_HEADING not in text
    assert B.ref_slot("", 0, B.PRODUCT_KIND) == ""


# ── the answer ──────────────────────────────────────────────────────────────


def answer(data=None, text=""):
    return SimpleNamespace(json=data, text=text)


def test_the_answer_is_read_and_cut_to_the_count():
    data = {"concept": {"name": "  Morning  light ", "direction": "Soft\n\nwarm"},
            "images": [{"title": "One", "prompt": "First"}, {"title": "Two", "prompt": "  "},
                       {"prompt": "Third"}, "junk", {"title": "Four", "prompt": "Fourth"}]}
    concept, cards = WR.parse(answer(data), count=2)
    assert concept == {"name": "Morning light", "direction": "Soft\nwarm"}
    assert [(c["n"], c["title"], c["prompt"]) for c in cards] == [(1, "One", "First"), (2, "", "Third")]
    assert all(c["edited"] is False and c["work_id"] is None for c in cards)
    _, every = WR.parse(answer(data), count=0)
    assert len(every) == 3
    text = 'Here it is: {"concept": {"name": "N"}, "ideas": [{"prompt": "P"}]} done'
    concept, cards = WR.parse(answer(None, text), count=0)
    assert concept["name"] == "N" and cards[0]["prompt"] == "P"
    with pytest.raises(AppError) as empty:
        WR.parse(answer({"concept": {"name": "x"}, "images": []}), count=3)
    assert empty.value.code == "ideas_empty"


def test_research_sources_and_block():
    raw = [{"title": "A", "url": "https://a.example/"}, {"title": "dup", "url": "https://a.example/"},
           {"title": "bad", "url": "javascript:alert(1)"}, {"url": "http://b.example/x"}, "junk"]
    assert R.clean_sources(raw) == [{"title": "A", "url": "https://a.example/"},
                                    {"title": "http://b.example/x", "url": "http://b.example/x"}]
    assert R.block("Soap", "  ") == ""
    assert R.block("Soap", "Summary") == f"{C.RESEARCH_HEADING}\nNICHE: Soap\n\nSummary"
    assert C.key_of("  Handmade   SOAP ") == C.key_of("handmade soap")


# ── the screen names of the setting ─────────────────────────────────────────


def test_every_setting_item_has_a_name_in_every_language():
    ids = {a["id"]: {i["id"] for i in a["items"]} for a in scene.axes()}
    for lang in ("ru", "uk", "en"):
        names = json.loads((WEB / "i18n" / "locales" / lang / "ideas.json").read_text(encoding="utf-8"))["ideas"]
        assert set(names["scene"]["axes"]) == set(ids), lang
        assert set(names["scene"]["items"]) == {i for items in ids.values() for i in items}, lang
        assert all(v["name"] and v["hint"] for v in names["scene"]["axes"].values()), lang
