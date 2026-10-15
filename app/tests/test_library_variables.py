import json

import pytest

from vf.core.errors import AppError
from vf.modules.library import variables as V


def test_extract_variables_keys_defaults_and_types():
    prompt = ("A {{Subject|red sneaker}} on {{background_color|#ffffff}} with {{brand}}, "
              "{{subject|ignored}} and {{accent_color}} {{Mood}}")
    found = V.extract_variables(prompt)
    assert [v["key"] for v in found] == ["subject", "background_color", "brand", "accent_color", "mood"]
    assert found[0] == {"key": "subject", "name": "Subject", "default": "red sneaker", "type": "subject"}
    assert found[1]["type"] == "color"
    assert found[2]["type"] == "brand"
    assert found[3]["type"] == "color"          # a colour by its name
    assert found[4]["type"] == "text"


def test_colour_detection_needs_a_whole_word():
    assert V.variable_type("discolour") == "text"
    assert V.variable_type("Колір фону") == "color"
    assert V.variable_type("hex") == "color"


def test_extract_variables_caps_at_twenty():
    prompt = " ".join(f"{{{{v{i}}}}}" for i in range(30))
    assert len(V.extract_variables(prompt)) == V.MAX_PROMPT_VARIABLES


def test_fill_variables_uses_value_then_default_and_tidies():
    prompt = "Bottle in {{bottle_color|emerald}} glass, label “{{brand}}” , {{effect}}."
    assert V.fill_variables(prompt, {"Bottle_Color": "amber", "brand": "SALT"}) == \
        "Bottle in amber glass, label “SALT”."
    # blank -> default; blank without default -> gone, and the punctuation is swept
    assert V.fill_variables(prompt, {"bottle_color": "  "}) == "Bottle in emerald glass, label."


def test_values_are_never_read_as_slots():
    assert V.fill_variables("Say {{a}}", {"a": "{{b|x}}"}) == "Say {{b|x}}"


def test_clean_values_accepts_dict_and_factory_list():
    assert V.clean_values({"Brand": "A", "x": None}) == {"brand": "A", "x": ""}
    assert V.clean_values([{"key": "Brand", "value": "B"}, "junk", {"value": "no key"}]) == {"brand": "B"}
    assert V.clean_values({"a": "x" * 5000})["a"] == "x" * V.MAX_VALUE_CHARS


def test_style_ref_round_trip():
    preset = {"id": 7, "title": "Neon", "prompt": "Neon {{brand|ACME}} on {{bg}}"}
    raw = V.make_style_ref(preset, {"brand": "SALT"}, extra="  warmer light ")
    assert raw.startswith(V.REF_PREFIX) and V.is_style_ref(raw)
    ref = V.parse_style_ref(raw)
    assert ref == {"preset": 7, "title": "Neon", "extra": "warmer light",
                   "vars": [{"key": "brand", "name": "brand", "value": "SALT"},
                            {"key": "bg", "name": "bg", "value": ""}]}
    assert V.parse_style_ref(json.loads(raw)) == ref
    assert V.parse_style_ref("plain words") is None
    assert V.parse_style_ref('{"preset": "x"}') is None
    assert V.parse_style_ref('{"preset": 0}') is None


def test_text_zones_parse_and_errors():
    assert V.parse_text_zones(None) is None
    assert V.parse_text_zones("   ") is None
    zones = V.parse_text_zones('{"canvas": {"w": 100}, "zones": [{"x": 1}, {"x": 2}]}')
    assert V.count_text_zones(zones) == 2
    assert V.parse_text_zones({"zones": []}) == {"zones": []}
    with pytest.raises(AppError) as err:
        V.parse_text_zones("{nope")
    assert err.value.code == "text_zones_invalid_json"
    with pytest.raises(AppError) as err:
        V.parse_text_zones("[1, 2]")
    assert err.value.code == "text_zones_not_an_object"
    with pytest.raises(AppError) as err:
        V.parse_text_zones({"zones": "x"})
    assert err.value.code == "text_zones_not_an_object"
    with pytest.raises(AppError) as err:
        V.parse_text_zones("{" + " " * V.MAX_TEXT_ZONES_CHARS + "}")
    assert err.value.code == "text_zones_too_large"
