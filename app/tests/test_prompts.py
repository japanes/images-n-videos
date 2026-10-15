from pathlib import Path

import pytest

from vf.core import prompts
from vf.core.errors import AppError

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(prompts, "PROMPTS_DIR", FIXTURES)
    monkeypatch.setattr(prompts, "_cache", None)
    yield prompts.load(force=True)
    prompts._cache = None


def test_latest_version_is_active(table):
    assert prompts.get("T_HELLO").version == 2
    assert prompts.get("T_HELLO", 1).version == 1


def test_render_fills_variables(table):
    rp = prompts.render("T_HELLO", 1, name="Ann")
    assert rp.text == "Say hello to Ann."
    assert (rp.code, rp.version, rp.role) == ("T_HELLO", 1, "prompt_enhance")


def test_missing_variable_is_an_error(table):
    with pytest.raises(AppError) as err:
        prompts.render("T_HELLO", name="Ann")
    assert err.value.code == "prompt_missing_vars"


def test_unknown_prompt(table):
    with pytest.raises(AppError):
        prompts.get("NOPE")


def test_schema_is_loaded_and_checked(table, database):
    assert prompts.get("T_SCHEMA").schema["type"] == "object"
    assert prompts.check_all() == []


def test_catalog(table):
    codes = {c["code"]: c for c in prompts.catalog()}
    assert codes["T_HELLO"]["versions"] == [1, 2]
    assert codes["T_HELLO"]["variables"] == ["language", "name"]


async def test_run_prompt_journals_code_and_version(table, database, no_sleep):
    from vf.core import db

    res = await prompts.run_prompt("T_SCHEMA", {"topic": "cats"}, purpose="test")
    assert res.json == {"items": ["stub items_0", "stub items_1"]}
    row = db.fetch_one("SELECT * FROM ai_calls")
    assert (row["prompt_code"], row["prompt_version"]) == ("T_SCHEMA", 1)
    assert row["role"] == "video_brief" or row["role"] is None


def test_folder_must_match_code(tmp_path):
    bad = tmp_path / "g" / "WRONG"
    bad.mkdir(parents=True)
    (bad / "v1.md").write_text("---\ncode: RIGHT\nversion: 1\n---\nx", encoding="utf-8")
    with pytest.raises(ValueError):
        prompts.load(tmp_path)


def test_repo_prompts_are_valid(database):
    prompts._cache = None
    assert prompts.check_all() == []
