import pytest

from vf.core import db, settings
from vf.core.google import GoogleCallError, PromptInfo, generate, journal
from vf.core.google.limiter import limiter


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


def _calls():
    return db.fetch_all("SELECT * FROM ai_calls ORDER BY id")


async def test_text_call_is_journaled_with_cost():
    res = await generate(purpose="test", contents=["hello there"], prompt=PromptInfo("T_X", 2),
                         refs=[("work", 7)])
    assert res.text.startswith("[stub answer]")
    assert res.stub is True
    rows = _calls()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "success" and row["stub"] == 1
    assert row["prompt_code"] == "T_X" and row["prompt_version"] == 2
    assert row["tokens_in"] > 0 and row["cost_usd"] > 0
    assert res.cost_usd == pytest.approx(row["cost_usd"])
    assert journal.cost_of("work", 7) == pytest.approx(row["cost_usd"])


async def test_json_answer_follows_schema():
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "n": {"type": "integer"}}}
    res = await generate(purpose="test", contents=["x"], response="json", schema=schema)
    assert set(res.json) == {"title", "n"}


async def test_image_answer():
    res = await generate(purpose="test", contents=["a cat"], response="image", aspect_ratio="16:9")
    data, mime = res.images[0]
    assert mime == "image/png" and data[:4] == b"\x89PNG"
    assert _calls()[0]["kind"] == "image"


async def test_retryable_error_is_retried_and_every_attempt_logged(fast):
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["[stub:error=server_error]"])
    rows = _calls()
    assert len(rows) == 3
    assert all(r["status"] == "error" and r["error_code"] == "server_error" for r in rows)
    assert [r["attempt"] for r in rows] == [1, 2, 3]
    assert err.value.call_ids == [r["id"] for r in rows]
    assert fast == [1.0, 2.0]


async def test_rate_limit_waits_a_minute(fast):
    with pytest.raises(GoogleCallError):
        await generate(purpose="test", contents=["[stub:error=rate_limited]"])
    assert fast == [60.0, 60.0]


async def test_non_retryable_error_stops_at_once():
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["[stub:error=permission_denied]"])
    assert err.value.code == "permission_denied"
    assert len(_calls()) == 1
    assert "simulated" in _calls()[0]["error_text"]


async def test_safety_block_is_free_and_not_repeated():
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["[stub:blocked] draw"], response="image")
    assert err.value.code == "safety_blocked"
    rows = _calls()
    assert len(rows) == 1 and rows[0]["status"] == "blocked" and rows[0]["cost_usd"] == 0


async def test_refusal_has_own_budget(fast):
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["[stub:refused] draw"], response="image")
    assert err.value.code == "refused"
    rows = _calls()
    assert len(rows) == 3
    assert all(r["error_code"] == "refused" for r in rows)
    assert fast == [30.0, 30.0]


async def test_daily_cap_blocks_live_spend(monkeypatch):
    settings.set("google.daily_cap_usd", 1.0)
    db.insert("ai_calls", {"created_at": db.now(), "attempt": 1, "kind": "text", "purpose": "x",
                           "status": "success", "stub": False, "cost_usd": 2.0})
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["hi"])
    assert err.value.code == "daily_cap"


async def test_cancel_before_request():
    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["hi"], cancel=lambda: True)
    assert err.value.code == "cancelled"
    assert _calls() == []


async def test_cancel_during_retry_pause():
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 1

    with pytest.raises(GoogleCallError) as err:
        await generate(purpose="test", contents=["[stub:error=network]"], cancel=cancel)
    assert err.value.code == "cancelled"


async def test_bound_refs_reach_every_attempt():
    with journal.bind_refs(("frame", 3)), pytest.raises(GoogleCallError):
        await generate(purpose="test", contents=["[stub:error=timeout]"])
    for row in _calls():
        assert journal.refs_of(row["id"]) == [("frame", 3)]


def test_recover_closes_running_rows(database):
    call_id = journal.start_call(kind="text", purpose="x", model_id="m")
    long_id = journal.start_call(kind="video", purpose="x", model_id="m")
    journal.update_call(long_id, operation_name="ops/1")
    assert journal.recover() == 1
    assert db.get("ai_calls", call_id)["status"] == "error"
    assert db.get("ai_calls", long_id)["status"] == "running"
    assert [r["id"] for r in journal.resumable_calls()] == [long_id]


def test_parse_json_text():
    from vf.core.google.gateway import parse_json_text

    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('Sure! [1, 2] done') == [1, 2]
    with pytest.raises(ValueError):
        parse_json_text("no json here")


def test_classify_google_errors():
    from vf.core.google import classify

    class Fake(Exception):
        def __init__(self, code, text):
            super().__init__(text)
            self.code = code

    assert classify(Fake(429, "RESOURCE_EXHAUSTED retryDelay: '17s'")).retry_after == 17
    assert classify(Fake(403, "Permission denied on resource")).code == "permission_denied"
    assert classify(Fake(403, "Billing has not been enabled for this project; enable billing")).code \
        == "billing_disabled"
    assert classify(Fake(404, "Publisher model not found")).code == "model_not_found"
    assert classify(Fake(503, "unavailable")).retryable
    assert classify(Fake(400, "INVALID_ARGUMENT")).code == "bad_request"
    assert classify(TimeoutError()).code == "timeout"
