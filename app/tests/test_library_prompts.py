"""Service prompt templates: every file the code relies on exists and renders."""

import re
from pathlib import Path

import pytest

from vf.core import prompts
from vf.core.errors import AppError
from vf.modules.library import templates

APP = Path(__file__).resolve().parents[1]

# The templates ported from the factory. Modules 04/05/06/09/11 build on these
# codes: a missing file must fail here, not at the first paid call.
LAYER_CODES = {
    "AVATAR_BASELINE", "AVATAR_IDENTITY_INPUT", "AVATAR_MASTER", "AVATAR_MASTER_RULE", "AVATAR_NEGATIVE",
    "AVATAR_REALISM", "AVATAR_SHOT", "AVATAR_VIDEO_NOTICE", "CAROUSEL_BLOCK_COUNT_FIXED",
    "CAROUSEL_BLOCK_COUNT_OPEN", "CAROUSEL_SLIDE_REWRITE", "CAROUSEL_SLIDE_REWRITE_BRIEF",
    "EDIT_LETTERING_REPLACE", "EDIT_LETTERING_RULE", "IMAGE_PART_CONTINUITY", "IMAGE_PART_CONTINUITY_NOTE_DEFAULT",
    "IMAGE_PART_CONTINUITY_SUBJECTS", "IMAGE_PART_EDIT_BASE", "IMAGE_PART_EDIT_MARKER", "IMAGE_PART_EDIT_REGION",
    "IMAGE_PART_FONT_SHEET", "IMAGE_PART_REFERENCES", "IMAGE_PART_REFERENCES_ANCHOR",
    "IMAGE_PART_REFERENCES_CONTINUITY", "IMAGE_PART_REFERENCES_SUBJECTS", "IMAGE_PART_STYLE_SAMPLE",
    "IMAGE_PART_STYLE_SAMPLE_BRAND", "IMAGE_PART_STYLE_SAMPLE_SUBJECTS", "IMAGE_PART_SUBJECTS_HEADER",
    "IMAGE_PART_SUBJECT_MULTI_PHOTOS", "IMAGE_SEGMENT_INPUT", "IMAGE_SLIDE_CONTINUITY", "IMAGE_SLIDE_FONT_SHEET",
    "IMAGE_SLIDE_STYLE_REFS", "IMAGE_SLIDE_STYLE_SAMPLE", "IMAGE_SLIDE_SUBJECTS", "PROMPT_BLOCK_AUTHOR_TEXT",
    "PROMPT_BLOCK_BRAND_COLORS", "PROMPT_BLOCK_BRAND_FONTS", "PROMPT_BLOCK_DRAW_TEXT", "PROMPT_BLOCK_FEEDBACK",
    "PROMPT_BLOCK_IDENTITY_ASSETS", "PROMPT_BLOCK_IMAGE_STYLE", "PROMPT_BLOCK_LANGUAGE",
    "PROMPT_BLOCK_LENGTH_LIMIT", "PROMPT_BLOCK_LOGO", "PROMPT_BLOCK_NO_LETTERING", "PROMPT_BLOCK_OUTPUT_SIZE",
    "PROMPT_BLOCK_OVERLAY_RULES", "PROMPT_BLOCK_OVERLAY_SYSTEM", "PROMPT_BLOCK_PHOTO_STYLE",
    "PROMPT_BLOCK_PROJECT_REFERENCES", "PROMPT_BLOCK_QUALITY", "PROMPT_BLOCK_SLIDE_POSITION",
    "PROMPT_BLOCK_SLIDE_TEXT", "PROMPT_BLOCK_STORY_BRIEF", "PROMPT_BLOCK_SUBJECTS", "PROMPT_BLOCK_TASK_ATTACHMENTS",
    "PROMPT_BLOCK_TONE_OF_VOICE", "PROMPT_BLOCK_VARIANT_DIVERSITY", "SHOT_IDEAS_INPUT", "SHOT_RESEARCH_INPUT",
    "SHOT_SCENE_RULE", "SLIDE_TEXT_HUMANIZER", "SLIDE_TEXT_PLACEMENT_MULTI", "SLIDE_TEXT_PLACEMENT_MULTI_AVOID",
    "SLIDE_TEXT_PLACEMENT_MULTI_SYSTEM", "SLIDE_TEXT_PLACEMENT_SINGLE", "SLIDE_TEXT_PLACEMENT_SINGLE_SYSTEM",
    "video_storyboard_reference", "video_storyboard_sheet", "video_storyboard_take",
}

# A prompt code passed as a string literal to any of these, anywhere in app/vf.
_CALL_RE = re.compile(
    r"(?:render_layer|layer_variables|prompts\.render|prompts\.get|run_prompt|PromptInfo)\(\s*"
    r"(?:code\s*=\s*)?[\"']([A-Za-z_][\w.]*)[\"']")


def test_all_layer_files_exist_and_load():
    table = prompts.load(force=True)
    missing = sorted(LAYER_CODES - set(table))
    assert missing == [], f"prompt files missing: {missing}"
    assert set(templates.layer_codes()) == LAYER_CODES
    for code in LAYER_CODES:
        pf = prompts.get(code)
        assert pf.role is None and pf.response == "text"
        assert pf.path.parts[-4] == "layers"


def test_prompt_files_have_no_problems():
    problems = prompts.check_all()
    assert [p for p in problems if any(code in p for code in LAYER_CODES)] == []
    assert templates.check_layers() == []


def test_every_prompt_code_in_the_code_has_a_file():
    known = set(prompts.load(force=True))
    used: dict[str, list[str]] = {}
    for path in (APP / "vf").rglob("*.py"):
        for code in _CALL_RE.findall(path.read_text(encoding="utf-8")):
            used.setdefault(code, []).append(str(path.relative_to(APP)))
    missing = {code: where for code, where in used.items() if code not in known}
    assert missing == {}, f"prompt codes without a file: {missing}"


@pytest.mark.parametrize("code", sorted(LAYER_CODES))
def test_each_layer_renders_with_its_values(code):
    needs = templates.layer_variables(code)
    values = {name: f"<{name}>" for name in needs["values"]}
    for name in needs["conditions"]:
        values.setdefault(name, f"<{name}>")
    for name in needs["lists"]:
        values[name] = ["a", "b"]
    text = templates.render_layer(code, values)
    assert text.strip()
    assert "{{" not in text and "%AVATAR" not in text


def test_layers_inside_layers_are_pasted():
    needs = templates.layer_variables("AVATAR_MASTER")
    assert {"AVATAR_MASTER_RULE", "AVATAR_BASELINE"} <= set(needs["layers"])
    body = prompts.get("AVATAR_MASTER").body
    assert "%AVATAR_MASTER_RULE%" in body
    pasted, used = templates.resolve_layers(body)
    assert "%AVATAR_MASTER_RULE%" not in pasted and "AVATAR_MASTER_RULE" in used
    assert prompts.get("AVATAR_MASTER_RULE").body.strip()[:40] in pasted


def test_unknown_token_stays_as_is():
    text, used = templates.resolve_layers("50% off and %NO_SUCH_LAYER% here")
    assert text == "50% off and %NO_SUCH_LAYER% here" and used == []


def test_conditions_else_and_lists():
    tpl = ("Head\n{{#if words}}\nWords: {{words}}\n{{else}}\nNo words.\n{{/if}}\n"
           "Tail{{#if n}} ({{n}}){{/if}}.\n{{#each items}}- {{this.name}} #{{@index}}\n{{/each}}")
    assert templates.render_text(tpl, {"words": "Hi", "n": 3, "items": [{"name": "a"}, {"name": "b"}]}) == \
        "Head\nWords: Hi\nTail (3).\n- a #0\n- b #1\n"
    assert templates.render_text(tpl, {"words": "  ", "n": 0, "items": []}) == "Head\nNo words.\nTail.\n"


def test_nested_conditions():
    tpl = "{{#if a}}A{{#if b}}B{{/if}}{{/if}}!"
    assert templates.render_text(tpl, {"a": 1, "b": 1}) == "AB!"
    assert templates.render_text(tpl, {"a": 1, "b": 0}) == "A!"
    assert templates.render_text(tpl, {"a": 0}) == "!"


def test_missing_value_is_an_error_but_not_inside_a_dropped_branch():
    with pytest.raises(AppError) as err:
        templates.render_text("Say {{words}} to {{who}}", {"who": "me"})
    assert err.value.code == "prompt_missing_vars" and err.value.details["missing"] == ["words"]
    assert templates.render_text("{{#if words}}Say {{words}}{{/if}}ok", {}) == "ok"


def test_values_are_not_rendered_again():
    assert templates.render_text("{{a}}", {"a": "{{b}} %AVATAR_NEGATIVE%"}) == "{{b}} %AVATAR_NEGATIVE%"
