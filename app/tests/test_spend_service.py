from datetime import date, timedelta

import pytest

from vf.core import db, files, settings
from vf.core.google import GoogleCallError, generate, journal
from vf.core.google.limiter import limiter
from vf.modules.spend import refs as spend_refs
from vf.modules.spend import service
from vf.modules.spend.service import Filters

TRIAL = service.TRIAL_SETTING


@pytest.fixture(autouse=True)
def fast(database, no_sleep):
    settings.set("google.max_rpm", 600)
    limiter._starts.clear()
    return no_sleep


def add_call(created_at: str, cost: float, *, kind: str = "image", purpose: str = "frame",
             status: str = "success", stub: bool = False, model_id: str | None = "gemini-x",
             refs=(), error_text: str | None = None, **extra) -> int:
    """A finished journal row with a fixed time and cost (through the real journal)."""
    call_id = journal.start_call(kind=kind, purpose=purpose, model_id=model_id, refs=refs, stub=stub,
                                 **{k: v for k, v in extra.items() if k in ("prompt_code", "prompt_version",
                                                                           "prompt_text", "attachments", "role")})
    journal.finish_call(call_id, status=status, cost_usd=cost, error_text=error_text,
                        error_code="server_error" if error_text else None)
    db.update("ai_calls", call_id, {"created_at": created_at})
    return call_id


def raw_sum(where_sql: str = "1 = 1", params=()) -> float:
    return round(float(db.fetch_value(f"SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE {where_sql}",
                                      params, 0.0)), 6)


def iso(day: date, hms: str = "12:00:00") -> str:
    return f"{day.isoformat()}T{hms}.000Z"


# ---------------------------------------------------------------- period bounds and days

def test_period_uses_local_days():
    # tz = +180 (Kyiv summer): the local day 2026-10-15 is 2026-10-14T21:00Z .. 2026-10-15T21:00Z
    inside = [add_call("2026-10-14T21:00:00.000Z", 1), add_call("2026-10-15T20:59:59.999Z", 2)]
    add_call("2026-10-14T20:59:59.999Z", 4)
    add_call("2026-10-15T21:00:00.000Z", 8)
    f = Filters(date_from=date(2026, 10, 15), date_to=date(2026, 10, 15), tz=180)
    res = service.list_calls(f)
    assert sorted(r["id"] for r in res["items"]) == sorted(inside)
    assert res["sum_usd"] == 3
    days = service.stats(f)["days"]
    assert days == [{"day": "2026-10-15", "usd": 3.0, "calls": 2, "by_kind": {"image": 3.0}}]


def test_days_grouped_by_local_day_and_kind():
    add_call("2026-10-01T23:30:00.000Z", 1, kind="image")  # 2026-10-02 at tz +60
    add_call("2026-10-02T10:00:00.000Z", 2, kind="video")
    add_call("2026-10-02T11:00:00.000Z", 0.5, kind="text")
    add_call("2026-10-04T10:00:00.000Z", 0, kind="list_models")
    f = Filters(date_from=date(2026, 10, 1), date_to=date(2026, 10, 4), tz=60)
    st = service.stats(f)
    assert [d["day"] for d in st["days"]] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    oct2 = st["days"][1]
    assert oct2["usd"] == 3.5 and oct2["calls"] == 3
    assert oct2["by_kind"] == {"image": 1.0, "video": 2.0, "text": 0.5}
    assert st["days"][3]["by_kind"] == {"other": 0.0}
    assert {k["key"]: k["usd"] for k in st["by_kind"]} == {"image": 1.0, "video": 2.0, "text": 0.5, "other": 0.0}
    assert st["total"] == {"calls": 4, "usd": 3.5, "failed": 0}


def test_bad_period_is_refused():
    with pytest.raises(service.AppError) as err:
        service.stats(Filters(date_from=date(2026, 10, 5), date_to=date(2026, 10, 1)))
    assert err.value.code == "invalid_period"


# ---------------------------------------------------------------- totals equal the journal

def test_screen_totals_equal_journal_sum():
    d = date(2026, 9, 10)
    add_call(iso(d), 0.04, kind="image", model_id="m-img")
    add_call(iso(d), 0.13, kind="image", model_id="m-img", status="error", error_text="boom")
    add_call(iso(d + timedelta(days=1)), 1.6, kind="video", model_id="m-vid", purpose="video_clip")
    add_call(iso(d + timedelta(days=2)), 0.002, kind="text", model_id="m-txt", purpose="research")
    add_call(iso(d + timedelta(days=2)), 5.0, kind="video", model_id="m-vid", stub=True)
    add_call(iso(d + timedelta(days=40)), 0.5, kind="image", model_id="m-img")

    cases = [
        (Filters(), "stub = 0", []),
        (Filters(include_stub=True), "1 = 1", []),
        (Filters(kind=["image"]), "stub = 0 AND kind = 'image'", []),
        (Filters(model_id=["m-vid"], include_stub=True), "model_id = 'm-vid'", []),
        (Filters(status=["error"]), "stub = 0 AND status = 'error'", []),
        (Filters(purpose=["research", "video_clip"]), "stub = 0 AND purpose IN ('research', 'video_clip')", []),
        (Filters(date_from=d, date_to=d + timedelta(days=2)),
         "stub = 0 AND created_at >= ? AND created_at < ?", [iso(d, "00:00:00"), iso(d + timedelta(days=3), "00:00:00")]),
    ]
    for f, sql, params in cases:
        expected = raw_sum(sql, params)
        st = service.stats(f)
        listed = service.list_calls(f)
        assert st["total"]["usd"] == pytest.approx(expected), f
        assert listed["sum_usd"] == pytest.approx(expected), f
        assert sum(day["usd"] for day in st["days"]) == pytest.approx(expected), f
        assert sum(k["usd"] for k in st["by_kind"]) == pytest.approx(expected), f
        assert sum(m["usd"] for m in st["by_model"]) == pytest.approx(expected), f
        assert listed["total"] == st["total"]["calls"]


def test_stub_calls_hidden_by_default():
    real = add_call(iso(date(2026, 10, 1)), 0.1)
    fake = add_call(iso(date(2026, 10, 1)), 9.0, stub=True)
    assert [r["id"] for r in service.list_calls(Filters())["items"]] == [real]
    shown = service.list_calls(Filters(include_stub=True))["items"]
    assert {r["id"] for r in shown} == {real, fake}
    assert next(r for r in shown if r["id"] == fake)["stub"] is True


def test_ref_filter_counts_each_call_once():
    one = add_call(iso(date(2026, 10, 1)), 1.0, refs=[("frame", 1), ("frame", 2), ("work", 7)])
    add_call(iso(date(2026, 10, 1)), 2.0, refs=[("frame", 3)])
    add_call(iso(date(2026, 10, 1)), 4.0)
    by_type = service.stats(Filters(ref_type="frame"))["total"]
    assert by_type == {"calls": 2, "usd": 3.0, "failed": 0}
    by_obj = service.list_calls(Filters(ref_type="work", ref_id=7))
    assert [r["id"] for r in by_obj["items"]] == [one] and by_obj["sum_usd"] == 1.0
    assert by_obj["items"][0]["refs"] == [{"type": "frame", "id": 1}, {"type": "frame", "id": 2},
                                          {"type": "work", "id": 7}]


def test_paging_keeps_totals():
    for i in range(7):
        add_call(f"2026-10-01T10:00:0{i}.000Z", 1.0)
    page = service.list_calls(Filters(), limit=3, offset=3)
    assert len(page["items"]) == 3 and page["total"] == 7 and page["sum_usd"] == 7.0
    newest = service.list_calls(Filters(), limit=1)["items"][0]
    assert newest["created_at"] == "2026-10-01T10:00:06.000Z"


# ---------------------------------------------------------------- summary cards

def test_summary_without_trial_date():
    settings.set(TRIAL, None, validate=False)
    add_call(iso(date(2026, 1, 1)), 10.0)
    add_call(iso(date(2026, 1, 2)), 2.5)
    add_call(iso(date(2026, 1, 2)), 100.0, stub=True)
    s = service.summary(tz=0)
    assert s["trial_started_on"] is None and s["days_left"] is None and s["trial_ends_on"] is None
    assert s["credit_usd"] == 300 and s["credit_days"] == 90
    assert s["spent_usd"] == 12.5 and s["remaining_usd"] == 287.5
    assert s["real_calls"] == 2 and s["stub_calls"] == 1
    assert s["spent_pct"] == pytest.approx(12.5 / 300 * 100, abs=0.01)
    assert s["billing_url"].startswith("https://console.cloud.google.com/billing/")


def test_summary_with_trial_date_counts_from_trial_start():
    today = service.local_today(0)
    start = today - timedelta(days=10)
    settings.set(TRIAL, start.isoformat(), validate=False)
    add_call(iso(start - timedelta(days=1)), 7.0)  # before the trial: not drawn from the credit
    add_call(iso(start), 20.0)
    add_call(iso(today), 30.0)
    s = service.summary(tz=0)
    assert s["trial_started_on"] == start.isoformat()
    assert s["trial_ends_on"] == (start + timedelta(days=90)).isoformat()
    assert s["days_left"] == 80 and s["expired"] is False
    assert s["spent_usd"] == 50 and s["spent_before_trial_usd"] == 7 and s["remaining_usd"] == 250


def test_summary_over_credit_and_expired():
    today = service.local_today(0)
    settings.set(TRIAL, (today - timedelta(days=200)).isoformat(), validate=False)
    settings.set("spend.credit_usd", 10.0)
    add_call(iso(today), 12.0)
    s = service.summary(tz=0)
    assert s["remaining_usd"] == 0 and s["over_usd"] == 2 and s["days_left"] == 0 and s["expired"] is True


def test_summary_ignores_unreadable_trial_date():
    settings.set(TRIAL, "someday", validate=False)
    assert service.summary()["trial_started_on"] is None


def test_summary_shows_daily_cap_and_today():
    settings.set("google.daily_cap_usd", 5.0)
    journal.finish_call(journal.start_call(kind="image", purpose="frame", model_id="x"), status="success",
                        cost_usd=1.25)
    s = service.summary()
    assert s["daily_cap_usd"] == 5.0 and s["spent_today_usd"] == 1.25
    assert s["cap_resets_at"].endswith("T00:00:00Z")


# ---------------------------------------------------------------- one call

def test_call_card_has_everything():
    image = files.save_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64, mime="image/png", name="ref.png")
    job_id = db.insert("jobs", {"kind": "spend.test", "group_name": "default", "status": "done", "title": "Test job",
                                "created_at": db.now(), "updated_at": db.now()})
    google_text = 'Quota exceeded for "aiplatform.googleapis.com/generate_content" — retry later.\nDetails: ×2'
    call_id = add_call(iso(date(2026, 10, 1)), 0.13, status="error", error_text=google_text,
                       prompt_code="STUDIO_FRAME", prompt_version=3, prompt_text="final prompt text",
                       role="frame_writer",
                       attachments=[{"mime": "image/png", "size": 72, "sha256": "ab", "file_id": image["id"]},
                                    {"mime": "image/jpeg", "size": 10, "sha256": "cd", "file_id": None}],
                       refs=[("file", image["id"]), ("job", job_id), ("unknown_t", 3)])
    card = service.get_call(call_id)
    assert card["error_text"] == google_text
    assert (card["prompt_code"], card["prompt_version"], card["prompt_text"]) == ("STUDIO_FRAME", 3,
                                                                                 "final prompt text")
    assert card["role"] == "frame_writer" and card["status"] == "error" and card["cost_usd"] == 0.13
    att = card["attachments"]
    assert att[0]["exists"] is True and att[0]["url"] == f"/files/{image['id']}"
    assert att[1]["exists"] is False and att[1]["mime"] == "image/jpeg"
    refs = {r["type"]: r for r in card["refs"]}
    assert refs["file"]["exists"] is True and refs["file"]["title"] == "ref.png"
    assert refs["file"]["url"] == f"/files/{image['id']}" and refs["file"]["link"] is None
    assert refs["job"]["title"] == "Test job"
    assert refs["unknown_t"] == {"type": "unknown_t", "id": 3, "title": None, "link": None, "url": None,
                                 "thumb_url": None, "exists": None}


def test_registered_ref_resolver_and_broken_one():
    spend_refs.register_ref("avatar_t", lambda i: {"title": f"Avatar {i}", "link": f"/avatars/{i}"})
    spend_refs.register_ref("broken_t", lambda i: 1 / 0)
    assert spend_refs.resolve("avatar_t", 5)["link"] == "/avatars/5"
    assert spend_refs.resolve("broken_t", 5)["exists"] is None


def test_missing_call_is_404():
    with pytest.raises(service.NotFound):
        service.get_call(424242)


async def test_failed_google_call_is_visible_with_its_error():
    with pytest.raises(GoogleCallError):
        await generate(purpose="frame", contents=["[stub:error=server_error]"], refs=[("work", 9)])
    rows = service.list_calls(Filters(include_stub=True, status=["error"]))["items"]
    assert len(rows) == 3 and all(r["error_text"] for r in rows)
    raw = db.fetch_one("SELECT error_text FROM ai_calls WHERE id = ?", (rows[0]["id"],))
    assert service.get_call(rows[0]["id"])["error_text"] == raw["error_text"]
    assert service.cost_of("work", 9)["failed"] == 3


async def test_finished_call_is_announced_for_live_update(monkeypatch):
    sent = []
    monkeypatch.setattr(journal.events, "publish", lambda t, d=None: sent.append((t, d)))
    await generate(purpose="frame", contents=["hello"])
    finished = [d for t, d in sent if t == "ai_call.finished"]
    assert len(finished) == 1 and finished[0]["cost_usd"] > 0


# ---------------------------------------------------------------- cost of an object, filter choices

def test_cost_of_object_splits_real_and_test_calls():
    add_call(iso(date(2026, 10, 1)), 1.5, refs=[("avatar", 4)])
    add_call(iso(date(2026, 10, 1)), 0.5, refs=[("avatar", 4)], status="blocked")
    add_call(iso(date(2026, 10, 1)), 3.0, refs=[("avatar", 4)], stub=True)
    c = service.cost_of("avatar", 4)
    assert c["usd"] == 2.0 and c["stub_usd"] == 3.0 and c["calls"] == 3 and c["stub_calls"] == 1
    assert c["failed"] == 1
    assert c["usd"] == journal.cost_of("avatar", 4, include_stub=False)


def test_filter_choices():
    add_call(iso(date(2026, 10, 1)), 1.0, kind="image", purpose="frame", refs=[("work", 1)])
    add_call(iso(date(2026, 10, 1)), 1.0, kind="video", purpose="video_clip", status="error", error_text="x")
    ch = service.filter_choices()
    assert ch["kinds"] == ["image", "video"]
    assert ch["purposes"] == ["frame", "video_clip"]
    assert ch["statuses"] == ["error", "success"]
    assert ch["models"] == [{"id": "gemini-x", "title": None}]
    assert ch["ref_types"] == ["work"]
