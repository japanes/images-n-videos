"""Module 02: availability check, price edits, general settings, frames."""

import json
import warnings
from pathlib import Path

import pytest

from vf.core import db, google, models_registry, settings
from vf.core.errors import AppError
from vf.core.google.boxes import box_2d_to_fractions
from vf.modules.models import service

WEB_LOCALES = Path(__file__).resolve().parents[2] / "web" / "i18n" / "locales"


@pytest.fixture
def fake_listing(monkeypatch):
    """Replace the free model listing with a fixed answer; returns the call log."""
    calls = []

    def install(names):
        async def fake(*, region="global", purpose="connection_check"):
            calls.append({"region": region, "purpose": purpose})
            return [{"name": n, "display_name": n} for n in names]

        monkeypatch.setattr(google, "list_models", fake)
        return calls

    return install


# ── availability ────────────────────────────────────────────────────────────


def test_names_are_normalized_and_matched():
    assert service._norm("publishers/google/models/Some-Model-001@002") == "some-model-001"
    assert service._matches("some-model-001", {"some-model-001"})
    assert service._matches("some-model-001", {"some-model"})
    assert service._matches("some-model", {"some-model-002"})
    assert not service._matches("some-model-pro", {"some-model"})
    assert not service._matches("some-model", {"other-model"})


async def test_stub_check_marks_every_model_available(database):
    result = await service.check_availability()
    assert result["checked"] is True and result["region"] == service.CHECK_REGION
    models = models_registry.list_models()
    assert all(m["available"] is True and m["available_checked_at"] for m in models)
    row = db.fetch_one("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 1")
    assert row["kind"] == "list_models" and row["purpose"] == service.CHECK_PURPOSE
    assert row["cost_usd"] == 0 and row["status"] == "success"


async def test_partial_listing_marks_the_rest_unavailable(database, fake_listing):
    models = models_registry.list_models()
    seen = [m["id"] for m in models[:2]]
    calls = fake_listing([f"publishers/google/models/{i}" for i in seen] + ["unrelated-thing"])
    result = await service.check_availability()
    assert calls == [{"region": service.CHECK_REGION, "purpose": service.CHECK_PURPOSE}]
    assert result["checked"] is True
    marks = {m["id"]: m["available"] for m in models_registry.list_models()}
    assert all(marks[i] is True for i in seen)
    assert all(ok is False for mid, ok in marks.items() if mid not in seen)


@pytest.mark.parametrize("names", [[], ["nothing-we-know", "another-unknown"]])
async def test_inconclusive_listing_marks_nothing(database, fake_listing, names):
    fake_listing(names)
    result = await service.check_availability()
    assert result["checked"] is False and result["items"] == []
    assert all(m["available"] is None for m in models_registry.list_models())


async def test_reset_forgets_marks(database):
    await service.check_availability()
    service.reset_availability()
    assert all(m["available"] is None and m["available_checked_at"] is None
               for m in models_registry.list_models())
    assert service.last_checked_at() is None


def test_unavailable_default_is_not_used(database):
    for kind in models_registry.KINDS:
        models = models_registry.list_models(kind)
        default = next(m for m in models if m["is_default"])
        assert service.effective_defaults()[kind] == default["id"]
        models_registry.set_availability({default["id"]: False})
        effective = service.effective_defaults()[kind]
        if len(models) > 1:
            assert effective is not None and effective != default["id"]


# ── price ───────────────────────────────────────────────────────────────────


def _model_with(field):
    return next(m for m in models_registry.list_models() if field in (m["seed_price"] or {}))


def test_price_keeps_only_real_changes(database):
    model = _model_with("input_per_1m")
    seed = model["seed_price"]
    out = service.set_price(model["id"], {"input_per_1m": seed["input_per_1m"] + 1,
                                          "output_per_1m": seed["output_per_1m"]})
    assert out["user_price"] == {"input_per_1m": seed["input_per_1m"] + 1}
    assert out["price"]["input_per_1m"] == seed["input_per_1m"] + 1
    assert out["price"]["output_per_1m"] == seed["output_per_1m"]
    same = service.set_price(model["id"], {"input_per_1m": seed["input_per_1m"]})
    assert same["user_price"] is None
    assert service.set_price(model["id"], None)["user_price"] is None


def test_price_table_per_resolution(database):
    model = _model_with("per_second")
    table = model["seed_price"]["per_second"]
    res = next(iter(table))
    out = service.set_price(model["id"], {"per_second": {res: table[res] + 0.01}})
    assert out["user_price"] == {"per_second": {res: pytest.approx(table[res] + 0.01)}}
    with pytest.raises(AppError) as err:
        service.set_price(model["id"], {"per_second": {"99k": 1}})
    assert err.value.code == "bad_price"


@pytest.mark.parametrize("price", [
    {"input_per_1m": -1}, {"input_per_1m": "1"}, {"input_per_1m": True}, {"input_per_1m": 1e9},
    {"input_per_1m": float("nan")}, {"image_output_tokens": {"1K": 1}}, {"no_such_field": 1}, ["x"],
])
def test_bad_prices_are_refused(database, price):
    model = _model_with("input_per_1m")
    with pytest.raises(AppError) as err:
        service.clean_price(model, price)
    assert err.value.code == "bad_price"


# ── general settings ────────────────────────────────────────────────────────


def test_general_settings_are_declared(database):
    defs = settings.definitions()
    assert defs["general.variants"].default == 3
    assert defs["general.max_attachments"].default == 10
    assert defs["general.text_language"].choices == service.TEXT_LANGUAGES
    assert defs["general.aspect_sizes"].meta == {"widget": "aspect_sizes"}
    with pytest.raises(AppError):
        settings.set("general.variants", 0)
    with pytest.raises(AppError):
        settings.set("general.text_language", "xx")


def test_output_size_falls_back_per_aspect(database):
    assert service.output_size("4:5") == (1080, 1350)
    assert service.output_size("9:16") == (1080, 1920)
    settings.set("general.aspect_sizes", {"4:5": [1200, 1500], "1:1": "junk", "9:16": [10, 99999]})
    assert service.output_size("4:5") == (1200, 1500)
    assert service.output_size("1:1") == (1080, 1080)
    assert service.output_size("9:16") == (1080, 1920)
    assert service.output_size("2:1") is None and service.output_size(None) is None
    settings.set("general.aspect_sizes", "not a dict")
    assert service.output_size("3:4") == (1080, 1440)


def _label(tree: dict, key: str, leaf: str):
    node = tree.get("settings", {}).get("keys", {})
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node.get(leaf) if isinstance(node, dict) else None


@pytest.mark.parametrize("lang", ["en", "ru", "uk"])
def test_core_and_general_settings_have_labels(lang):
    path = WEB_LOCALES / lang / "settings.json"
    if not path.parent.exists():
        pytest.skip("web sources are not mounted")
    tree = json.loads(path.read_text(encoding="utf-8"))
    keys = [k for k in settings.definitions() if k.startswith(("google.", "jobs.limit.", "general."))]
    assert "google.max_rpm" in keys and "general.variants" in keys
    missing = [k for k in keys if not _label(tree, k, "label") or not _label(tree, k, "help")]
    assert missing == []


@pytest.mark.parametrize("lang", ["en", "ru", "uk"])
def test_other_module_settings_labels_are_a_soft_check(lang):
    """Keys of other modules come and go as they land: a missing label only warns
    (the settings screen falls back to the key or to ``meta.label_key``)."""
    path = WEB_LOCALES / lang / "settings.json"
    if not path.parent.exists():
        pytest.skip("web sources are not mounted")
    tree = json.loads(path.read_text(encoding="utf-8"))
    strict = ("google.", "jobs.limit.", "general.")
    # "test." keys are declared by other tests of the settings core, not by modules.
    others = [k for k, d in settings.definitions().items()
              if d.public and not k.startswith(strict) and not k.startswith("test.")]
    missing = [k for k in others
               if not settings.definitions()[k].meta.get("label_key") and not _label(tree, k, "label")]
    if missing:
        warnings.warn(f"{lang}/settings.json has no label for: {', '.join(sorted(missing))}", stacklevel=1)


# ── frames from Gemini ──────────────────────────────────────────────────────


def test_box_2d_is_y_first_on_a_1000_grid():
    assert box_2d_to_fractions([200, 100, 450, 400]) == pytest.approx({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25})
    assert box_2d_to_fractions([450, 400, 200, 100]) == pytest.approx({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25})
    assert box_2d_to_fractions([-50, 900, 500, 1200]) == pytest.approx({"x": 0.9, "y": 0.0, "w": 0.1, "h": 0.5})
    assert box_2d_to_fractions({"x": 100, "y": 200, "width": 300, "height": 250}) == pytest.approx(
        {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25})
    assert box_2d_to_fractions([0.2, 0.1, 0.45, 0.4], scale=1) == pytest.approx(
        {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25})


@pytest.mark.parametrize("raw", [None, "box", [1, 2, 3], [100, 100, 100, 400], [1200, 0, 1500, 10],
                                 {"x": 1, "y": 1, "w": 0, "h": 5}, ["a", "b", "c", "d"]])
def test_empty_boxes_give_none(raw):
    assert box_2d_to_fractions(raw) is None
