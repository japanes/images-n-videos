"""Module 02 over HTTP: models screen, roles, price, settings."""

import httpx
import pytest

from vf.core import db, settings
from vf.core.google import generate
from vf.core.google.limiter import limiter


def test_check_and_overview(client):
    before = client.get("/api/models/overview").json()
    assert before["checked_at"] is None and set(before["effective"]) == {"image", "video", "text"}
    res = client.post("/api/models/check")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["checked"] is True and body["checked_at"]
    assert all(m["available"] is True for m in client.get("/api/models").json()["items"])
    after = client.delete("/api/models/check").json()
    assert after["checked_at"] is None
    assert all(m["available"] is None for m in client.get("/api/models").json()["items"])


def test_unavailable_default_is_replaced_in_overview(client):
    images = client.get("/api/models", params={"kind": "image"}).json()["items"]
    default = next(m for m in images if m["is_default"])
    from vf.core import models_registry

    models_registry.set_availability({default["id"]: False})
    effective = client.get("/api/models/overview").json()["effective"]["image"]
    assert effective != default["id"]
    listed = {m["id"]: m for m in client.get("/api/models", params={"kind": "image"}).json()["items"]}
    assert listed[default["id"]]["available"] is False and listed[default["id"]]["is_default"] is True


def test_price_endpoint(client):
    model = next(m for m in client.get("/api/models").json()["items"] if "input_per_1m" in m["seed_price"])
    new = model["seed_price"]["input_per_1m"] + 0.5
    res = client.put(f"/api/models/{model['id']}/price", json={"price": {"input_per_1m": new}})
    assert res.status_code == 200, res.text
    assert res.json()["price"]["input_per_1m"] == new
    bad = client.put(f"/api/models/{model['id']}/price", json={"price": {"input_per_1m": -2}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_price"
    unknown = client.put("/api/models/no-such-model/price", json={"price": None})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "model_unknown"
    reset = client.put(f"/api/models/{model['id']}/price", json={"price": None}).json()
    assert reset["user_price"] is None and reset["price"]["input_per_1m"] == model["seed_price"]["input_per_1m"]


def test_general_settings_are_served(client):
    items = {i["key"]: i for i in client.get("/api/settings").json()["items"]}
    for key in ("general.variants", "general.max_attachments", "general.text_language", "general.aspect_sizes"):
        assert items[key]["group"] == "general"
    assert items["general.aspect_sizes"]["meta"]["widget"] == "aspect_sizes"
    bad = client.put("/api/settings", json={"general.variants": 99})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_setting"
    ok = client.put("/api/settings", json={"general.variants": 4}).json()
    assert ok["values"]["general.variants"] == 4
    back = client.put("/api/settings", json={"general.variants": None}).json()
    assert back["values"]["general.variants"] == 3


@pytest.fixture
def api(database, no_sleep, cfg):
    """The app over ASGI without its lifespan (the database fixture already set it up)."""
    from vf.main import create_app

    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    app = create_app(cfg, run_background=False)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_role_change_moves_the_next_call_to_that_model(api):
    async with api as http:
        roles = (await http.get("/api/models/roles")).json()["items"]
        role = next(r for r in roles if r["role"] == "vision_describe")
        assert role["model_id"] and role["override"] is None
        others = [c for c in role["candidates"] if c != role["model_id"]]
        if not others:
            pytest.skip("the registry has one text model that fits this role")
        target = others[0]
        res = await http.put("/api/models/roles/vision_describe", json={"model_id": target})
        assert res.status_code == 200, res.text
        await generate(purpose="models_test", contents=["describe"], role="vision_describe")
        row = db.fetch_one("SELECT model_id, role FROM ai_calls ORDER BY id DESC LIMIT 1")
        assert row == {"model_id": target, "role": "vision_describe"}

        await http.put("/api/models/roles/vision_describe", json={"model_id": None})
        await generate(purpose="models_test", contents=["describe"], role="vision_describe")
        row = db.fetch_one("SELECT model_id FROM ai_calls ORDER BY id DESC LIMIT 1")
        assert row["model_id"] == role["model_id"]
