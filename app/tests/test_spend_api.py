from vf.core import db
from vf.core.google import journal


def _call(created_at: str, cost: float, **kw) -> int:
    call_id = journal.start_call(kind=kw.get("kind", "image"), purpose=kw.get("purpose", "frame"),
                                 model_id=kw.get("model_id"), stub=kw.get("stub", False), refs=kw.get("refs", ()))
    journal.finish_call(call_id, status=kw.get("status", "success"), cost_usd=cost,
                        error_text=kw.get("error_text"))
    db.update("ai_calls", call_id, {"created_at": created_at})
    return call_id


def test_screen_endpoints(client):
    first = _call("2026-10-01T09:00:00.000Z", 0.04, model_id="gemini-2.5-flash-image")
    _call("2026-10-02T09:00:00.000Z", 1.2, kind="video", purpose="video_clip", refs=[("video", 2)])
    _call("2026-10-02T10:00:00.000Z", 3.0, stub=True)
    params = {"date_from": "2026-10-01", "date_to": "2026-10-03", "tz": 0}

    stats = client.get("/api/spend/stats", params=params).json()
    assert stats["total"]["usd"] == 1.24 and len(stats["days"]) == 3

    with_stub = client.get("/api/spend/stats", params={**params, "include_stub": "true"}).json()
    assert with_stub["total"]["usd"] == 4.24

    calls = client.get("/api/spend/calls", params={**params, "kind": "image"}).json()
    assert [r["id"] for r in calls["items"]] == [first] and calls["sum_usd"] == 0.04
    assert "prompt_text" not in calls["items"][0] and "response_json" not in calls["items"][0]

    card = client.get(f"/api/spend/calls/{first}").json()
    assert card["id"] == first and card["model_id"] == "gemini-2.5-flash-image"

    by_ref = client.get("/api/spend/calls", params={"ref_type": "video", "ref_id": 2}).json()
    assert by_ref["total"] == 1 and by_ref["sum_usd"] == 1.2

    cost = client.get("/api/spend/cost", params={"ref_type": "video", "ref_id": 2}).json()
    assert cost["usd"] == 1.2 and cost["calls"] == 1

    choices = client.get("/api/spend/filters").json()
    assert set(choices["kinds"]) == {"image", "video"}

    summary = client.get("/api/spend/summary", params={"tz": 120}).json()
    assert summary["spent_usd"] == 1.24 and summary["remaining_usd"] == 298.76 and summary["stub_calls"] == 1
    assert summary["stub_mode"] is True and summary["project_id"] is None


def test_bad_requests(client):
    assert client.get("/api/spend/stats", params={"date_from": "yesterday"}).json()["error"]["code"] == \
        "invalid_date"
    res = client.get("/api/spend/calls", params={"date_from": "2026-10-05", "date_to": "2026-10-01"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_period"
    assert client.get("/api/spend/summary", params={"tz": 5000}).json()["error"]["code"] == "invalid_tz"
    assert client.get("/api/spend/calls/999999").status_code == 404
    assert client.get("/api/spend/calls", params={"limit": 0}).status_code in (400, 422)


def test_spend_settings(client):
    values = client.get("/api/settings").json()["values"]
    assert values["spend.credit_usd"] == 300 and values["spend.credit_days"] == 90
    assert "google.daily_cap_usd" in values
    res = client.put("/api/settings", json={"spend.credit_usd": 250, "google.daily_cap_usd": 20})
    assert res.status_code == 200
    assert client.get("/api/spend/summary").json()["credit_usd"] == 250
    assert client.get("/api/spend/summary").json()["daily_cap_usd"] == 20
    assert client.put("/api/settings", json={"spend.credit_usd": -1}).status_code == 400
    assert client.put("/api/settings", json={"spend.credit_days": 0}).status_code == 400
