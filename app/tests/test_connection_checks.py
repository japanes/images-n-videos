"""Module 01: the connection checks (stub mode) and what the screen shows."""

import dataclasses
import json

import pytest
from connection_keys import make_key, upload

from vf.core import db, models_registry, prompts, settings
from vf.core.errors import AppError
from vf.core.google import GoogleCallError
from vf.core.google.limiter import limiter
from vf.modules.connection import service


@pytest.fixture
def keyed(client):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    assert upload(client, make_key()).status_code == 200
    return client


@pytest.fixture
def google_says(monkeypatch):
    """Make the stub fail the given prompt with a Google error code."""
    def arm(code: str, error: str):
        real = prompts.render

        def render(c, version=None, **values):
            rp = real(c, version, **values)
            if c == code:
                rp = dataclasses.replace(rp, text=f"{rp.text} [stub:error={error}]")
            return rp

        monkeypatch.setattr(prompts, "render", render)
    return arm


def caps(state):
    return {c["id"]: c for c in state["capabilities"]}


def calls():
    return db.fetch_all("SELECT * FROM ai_calls ORDER BY id")


def test_checks_need_a_key(client):
    for path in ("/api/connection/check", "/api/connection/check/image"):
        resp = client.post(path)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "no_key"
    assert calls() == []


def test_basic_checks_pass_in_stub_mode(keyed):
    resp = keyed.post("/api/connection/check")
    assert resp.status_code == 200, resp.text
    state = resp.json()
    for name in ("token", "models", "text"):
        assert state["checks"][name]["status"] == "ok", name
    assert state["checks"]["image"] is None
    assert state["last_check_at"]

    ticks = caps(state)
    assert ticks["text"]["state"] == "ok"
    assert ticks["images"]["state"] == "seen"
    assert ticks["veo"]["state"] == "seen"
    assert ticks["omni"]["state"] == "unknown"      # Omni answers only to a live request
    assert ticks["veo"]["region"] == "us-central1"
    assert ticks["omni"]["region"] == "global"
    assert ticks["omni"]["check_seconds"] == 3      # the shortest clip the seed allows: priced before the click

    rows = calls()
    assert [r["kind"] for r in rows] == ["token", "list_models", "text"]
    assert {r["purpose"] for r in rows} == {"connection_check"}
    assert {r["status"] for r in rows} == {"success"}
    text_call = rows[-1]
    assert text_call["prompt_code"] == "connection.check_text"
    assert text_call["prompt_version"] == 1
    assert models_registry.get(ticks["text"]["model_id"])["available"] is True
    assert models_registry.get(ticks["veo"]["model_id"])["available"] is True
    assert models_registry.get(ticks["omni"]["model_id"])["available"] is True  # listed by the stub


def test_broken_token_stops_the_chain(keyed, monkeypatch):
    raw = "('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant'})"

    async def fail(**_):
        raise GoogleCallError("invalid_grant", raw)

    monkeypatch.setattr(service.token, "check_token", fail)
    state = keyed.post("/api/connection/check").json()
    assert state["checks"]["token"]["status"] == "error"
    assert state["checks"]["token"]["error"]["code"] == "invalid_grant"
    assert state["checks"]["token"]["error"]["google_message"] == raw   # Google's words, untouched
    assert state["checks"]["models"]["status"] == "skipped"
    assert state["checks"]["text"]["status"] == "skipped"
    assert {c["state"] for c in state["capabilities"]} == {"blocked"}
    assert {c["blocked_by"] for c in state["capabilities"]} == {"invalid_grant"}
    assert calls() == []  # the faked token call made no journal row; nothing else ran


def test_real_token_call_is_journaled(keyed):
    keyed.post("/api/connection/check")
    row = calls()[0]
    assert row["kind"] == "token" and row["cost_usd"] == 0 and row["status"] == "success"


@pytest.mark.parametrize("code", ["billing_disabled", "api_disabled", "permission_denied"])
def test_project_errors_show_on_every_tick(keyed, google_says, code):
    google_says(service.TEXT_PROMPT, code)
    state = keyed.post("/api/connection/check").json()
    text = state["checks"]["text"]
    assert text["status"] == "error"
    assert text["error"]["code"] == code
    assert "simulated" in text["error"]["google_message"]
    assert text["error"]["call_ids"]
    ticks = caps(state)
    assert ticks["text"]["state"] == "error"
    for cap in ("images", "veo", "omni"):
        assert ticks[cap]["state"] == "blocked"
        assert ticks[cap]["blocked_by"] == code
    failed = calls()[-1]
    assert failed["status"] == "error" and failed["error_code"] == code
    assert failed["purpose"] == "connection_check"


def test_text_model_not_found_marks_it_unavailable(keyed, google_says):
    google_says(service.TEXT_PROMPT, "model_not_found")
    state = keyed.post("/api/connection/check").json()
    text = state["checks"]["text"]
    assert text["error"]["code"] == "model_not_found"
    failed = text["model_id"]
    assert models_registry.get(failed)["available"] is False
    ticks = caps(state)
    # The app moves on to the next usable text model; until checked its tick is unknown.
    if ticks["text"]["model_id"] == failed:
        assert ticks["text"]["state"] == "error"
    else:
        assert ticks["text"]["state"] == "unknown"
    assert ticks["images"]["state"] != "blocked"  # the project itself works


def test_rate_limit_is_reported_not_blocking(keyed, google_says, no_sleep):
    google_says(service.TEXT_PROMPT, "rate_limited")
    state = keyed.post("/api/connection/check").json()
    assert state["checks"]["text"]["error"]["code"] == "rate_limited"
    assert caps(state)["images"]["state"] != "blocked"


def test_test_picture(keyed):
    resp = keyed.post("/api/connection/check/image")
    assert resp.status_code == 200, resp.text
    state = resp.json()
    assert state["checks"]["image"]["status"] == "ok"
    assert state["test_image"]["id"] == state["checks"]["image"]["file_id"]
    assert caps(state)["images"]["state"] == "ok"
    row = calls()[-1]
    assert row["kind"] == "image"
    assert row["purpose"] == "connection_check"
    assert row["prompt_code"] == "connection.check_image"


def test_test_picture_error_then_fixed(keyed, google_says, monkeypatch):
    google_says(service.IMAGE_PROMPT, "billing_disabled")
    state = keyed.post("/api/connection/check/image").json()
    assert state["checks"]["image"]["error"]["code"] == "billing_disabled"
    assert caps(state)["images"]["state"] == "error"
    assert state["test_image"] is None

    monkeypatch.undo()  # billing fixed: a new basic run forgets the old project error
    state = keyed.post("/api/connection/check").json()
    assert state["checks"]["image"] is None
    assert caps(state)["images"]["state"] == "seen"


def test_omni_waits_for_the_video_module(keyed, monkeypatch):
    monkeypatch.setitem(service._omni_check, "fn", None)
    resp = keyed.post("/api/connection/check/omni")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "check_unavailable"
    assert keyed.get("/api/connection").json()["omni_check_available"] is False


def test_omni_check_through_the_hook(keyed, monkeypatch):
    seen = []

    async def ok(model):
        seen.append(model)
        return {"cost_usd": 0.3}

    monkeypatch.setitem(service._omni_check, "fn", ok)
    state = keyed.post("/api/connection/check/omni").json()
    assert seen and seen[0]["api"] == "omni"
    assert state["omni_check_available"] is True
    assert state["checks"]["omni"]["status"] == "ok"
    assert caps(state)["omni"]["state"] == "ok"

    async def missing(model):
        raise GoogleCallError("model_not_found", "404 Publisher Model ... was not found", http_status=404)

    monkeypatch.setitem(service._omni_check, "fn", missing)
    state = keyed.post("/api/connection/check/omni").json()
    omni = caps(state)["omni"]
    assert omni["state"] == "error"
    assert omni["error"]["code"] == "model_not_found"
    assert models_registry.get(omni["model_id"])["available"] is False


async def test_second_check_while_running_is_refused(client):
    upload(client, make_key())
    async with service._check_lock:
        with pytest.raises(AppError) as caught:
            await service.run_basic_checks()
    assert caught.value.code == "check_running"


def test_results_stored_in_the_row(keyed):
    keyed.post("/api/connection/check")
    row = db.fetch_one("SELECT * FROM google_credentials")
    assert row["last_check_at"]
    results = row["last_check_result_json"]
    if isinstance(results, str):
        results = json.loads(results)
    assert set(results) == {"token", "models", "text"}
