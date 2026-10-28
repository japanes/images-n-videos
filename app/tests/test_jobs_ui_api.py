"""Jobs page API: filtered list, overview (counts, group limits), service health."""

import httpx
import pytest

from vf.core import db, jobs, settings
from vf.modules.jobs_ui import service


def _row(status, *, kind="test.ui_any", group="image", title=None, ref=None, **extra):
    now = db.now()
    values = {"kind": kind, "group_name": group, "status": status, "title": title, "attempts": 1,
              "created_at": now, "updated_at": now, **extra}
    if ref:
        values["ref_type"], values["ref_id"] = ref
    if status in jobs.FINISHED:
        values["finished_at"] = now
    return db.insert("jobs", values)


@pytest.fixture
def filled(database):
    ids = {
        "done": _row("done", title="Cat on a sofa", ref=("frame", 7)),
        "error": _row("error", title="Video of a dog", group="video", kind="test.ui_video",
                      error_code="rate_limited", error="429 RESOURCE_EXHAUSTED"),
        "interrupted": _row("interrupted", error_code="interrupted"),
        "cancelled": _row("cancelled"),
        "queued": _row("queued", group="text", kind="test.ui_text"),
        "running": _row("running", group="video", kind="test.ui_video"),
    }
    return ids


def test_list_filters(filled):
    def ids(**kw):
        return [i["id"] for i in service.list_page(**kw)["items"]]

    assert ids() == sorted(filled.values(), reverse=True)
    assert set(ids(status="active")) == {filled["queued"], filled["running"]}
    assert set(ids(status="problems")) == {filled["error"], filled["interrupted"]}
    assert set(ids(status="finished")) == {filled[s] for s in ("done", "error", "interrupted", "cancelled")}
    assert ids(status="cancelled") == [filled["cancelled"]]
    assert set(ids(group="video")) == {filled["error"], filled["running"]}
    assert ids(kind="test.ui_text") == [filled["queued"]]
    assert ids(ref_type="frame", ref_id=7) == [filled["done"]]
    assert ids(q="DOG") == [filled["error"]]
    assert ids(q=str(filled["cancelled"])) == [filled["cancelled"]]


def test_list_item_flags_and_paging(filled):
    page = service.list_page(limit=4)
    assert len(page["items"]) == 4 and page["has_more"] is True
    rest = service.list_page(limit=4, before_id=page["next_before_id"])
    assert len(rest["items"]) == 2 and rest["has_more"] is False and rest["next_before_id"] is None
    by_id = {i["id"]: i for i in page["items"] + rest["items"]}
    err = by_id[filled["error"]]
    assert err["retryable"] and not err["cancellable"]
    assert err["error"] == "429 RESOURCE_EXHAUSTED" and err["error_code"] == "rate_limited"
    assert by_id[filled["running"]]["cancellable"] and not by_id[filled["running"]]["retryable"]
    assert "updated_at" in err and "payload_json" not in err


def test_unknown_status_filter_is_rejected(database):
    with pytest.raises(Exception) as exc:
        service.list_page(status="nope")
    assert getattr(exc.value, "code", None) == "validation"


def test_overview_counts_and_group_limits(filled):
    settings.set("jobs.limit.video", 1)
    data = service.overview()
    c = data["counts"]
    assert c["active"] == 2 and c["finished"] == 4 and c["problems"] == 2 and c["all"] == 6
    groups = {g["group"]: g for g in data["groups"]}
    assert set(jobs.GROUP_DEFAULTS) <= set(groups)
    assert groups["video"] == {"group": "video", "limit": 1, "setting": "jobs.limit.video",
                               "running": 1, "queued": 0}
    assert groups["text"]["queued"] == 1 and groups["stt"]["limit"] == 1
    kinds = {k["kind"]: k for k in data["kinds"]}
    assert kinds["test.ui_video"]["count"] == 2
    assert data["settings"]["jobs.backup_keep"] == 7
    assert data["backups"] == {"count": 0, "last": None}


def _mock_services(monkeypatch, routes):
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        answer = routes[request.url.host]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_health_reports_each_service(client, monkeypatch):
    _mock_services(monkeypatch, {
        "render.test": (200, {"ok": True, "version": "0.4.0", "ffmpeg": "5.1", "queue": {"running": 1, "queued": 3},
                              "secret": "x"}),
        "stt.test": httpx.ConnectError("refused"),
    })
    res = client.get("/api/jobs_ui/health")
    assert res.status_code == 200
    by_name = {s["name"]: s for s in res.json()["services"]}
    assert by_name["render"]["state"] == "ok"
    assert by_name["render"]["details"] == {"ffmpeg": "5.1", "queue": {"running": 1, "queued": 3}}
    assert by_name["stt"]["state"] == "unreachable" and by_name["stt"]["error_code"] == "stt_unavailable"


def test_health_shows_render_problem_text(client, monkeypatch):
    _mock_services(monkeypatch, {
        "render.test": (503, {"ok": False, "version": "0.4.0", "error": "ffmpeg is not available: ENOENT"}),
        "stt.test": (200, {"ok": True, "version": "0.1.0", "busy": True}),
    })
    by_name = {s["name"]: s for s in client.get("/api/jobs_ui/health").json()["services"]}
    assert by_name["render"]["state"] == "problem"
    assert by_name["render"]["message"] == "ffmpeg is not available: ENOENT"
    assert by_name["stt"]["details"] == {"busy": True}


def test_routes_list_and_overview(client):
    done = _row("done", title="Picture")
    res = client.get("/api/jobs_ui/list", params={"status": "finished"})
    assert res.status_code == 200
    assert [i["id"] for i in res.json()["items"]] == [done]
    assert client.get("/api/jobs_ui/list", params={"status": "bogus"}).status_code == 422
    assert client.get("/api/jobs_ui/list", params={"limit": 0}).status_code == 422
    ov = client.get("/api/jobs_ui/overview").json()
    assert ov["counts"]["done"] == 1 and ov["runner_alive"] is True
