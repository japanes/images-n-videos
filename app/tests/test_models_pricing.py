import json

import pytest

from vf.core import models_registry as reg
from vf.core import pricing
from vf.core.errors import AppError


def _seed():
    return reg.load_seed()


def test_seed_sets_one_default_per_kind(database):
    for kind in reg.KINDS:
        defaults = [m for m in reg.list_models(kind) if m["is_default"]]
        assert len(defaults) == 1, kind


def test_user_default_survives_reseed(database):
    other = next(m for m in reg.list_models("image") if not m["is_default"])
    reg.set_default(other["id"])
    reg.seed()
    assert reg.default_for("image")["id"] == other["id"]


def test_removed_model_is_flagged(database):
    data = _seed()
    gone = data["models"].pop()
    counts = reg.seed(data)
    assert counts["removed"] == 1
    assert reg.find(gone["id"])["removed"] is True
    assert gone["id"] not in [m["id"] for m in reg.list_models()]


def test_cannot_disable_default(database):
    with pytest.raises(AppError):
        reg.set_enabled(reg.default_for("text")["id"], False)


def test_resolve_checks_kind(database):
    text_id = reg.default_for("text")["id"]
    with pytest.raises(AppError) as err:
        reg.resolve("image", text_id)
    assert err.value.code == "model_wrong_kind"


def test_roles_use_default_text_model(database):
    default = reg.default_for("text")["id"]
    for item in reg.roles_overview():
        assert item["model_id"] == default


def test_role_override(database):
    candidates = [m for m in reg.list_models("text") if reg.suits_role(m, "research")]
    chosen = candidates[-1]
    reg.set_role_model("research", chosen["id"])
    assert reg.model_for_role("research")["id"] == chosen["id"]
    reg.set_role_model("research", None)
    assert reg.model_for_role("research")["id"] == reg.default_for("text")["id"]


def test_user_price_overrides_seed(database):
    model = reg.default_for("text")
    reg.set_user_price(model["id"], {"input_per_1m": 9})
    priced = reg.get(model["id"])
    assert priced["price"]["input_per_1m"] == 9
    assert priced["price"]["output_per_1m"] == model["seed_price"]["output_per_1m"]


def test_video_resolutions_parse(database):
    for model in reg.list_models("video"):
        table = reg.video_resolutions(model)
        assert table, model["id"]
        assert all(table.values())


def test_token_and_search_cost():
    price = {"input_per_1m": 1, "output_per_1m": 10, "search_per_request": 0.01}
    model = {"api": "generate_content", "price": price}
    assert pricing.call_cost(model, tokens_in=1_000_000, tokens_out=100_000, search_requests=2) == 2.02
    assert pricing.call_cost(model, tokens_in=10, tokens_out=10, blocked=True) == 0


def test_veo_cost_by_resolution():
    model = {"api": "veo", "price": {"per_second": {"720p": 0.1, "1080p": 0.2}}}
    assert pricing.call_cost(model, video_seconds=8, video_resolution="1080p") == 1.6


def test_omni_cost_from_seconds():
    model = {"api": "omni", "price": {"input_per_1m": 0, "output_per_1m": 10, "output_tokens_per_second": 1000}}
    assert pricing.call_cost(model, video_seconds=5) == pytest.approx(0.05)


def test_estimates_are_positive(database):
    assert pricing.estimate_image(reg.default_for("image"), count=3) > 0
    assert pricing.estimate_text(reg.default_for("text"), search=True) > 0
    video = reg.default_for("video")
    assert pricing.estimate_video(video, seconds=8, resolution="720p") > 0


def test_seed_file_is_valid_json():
    data = _seed()
    assert data["schema"] == 1
    json.dumps(data)
    ids = [m["id"] for m in data["models"]]
    assert len(ids) == len(set(ids))
