"""Updates screen API (module 14, app side) against a fake updater."""

import json

import httpx
import pytest

from vf.core import db, jobs

TOKEN = "updater-secret-token-123"


def _status(**over):
    base = {
        "current_version": "1.2.3",
        "installed_version": "1.2.3",
        "channel": "stable",
        "auto": True,
        "time": "03:00",
        "tz": "UTC",
        "dev": False,
        "last_check_at": "2026-10-15T10:00:00Z",
        "last_check_error": None,
        "available": [
            {"version": "1.5.0", "prerelease": False, "published_at": "2026-10-14T10:00:00Z",
             "notes_md": "## New\n- faster <script>x</script>", "html_url": "https://github.com/a/b/releases/1.5.0",
             "installable": False, "min_upgrade_from": "1.4.0", "failed_before": False, "extra": "dropped"},
            {"version": "1.4.0", "prerelease": False, "published_at": "2026-10-01T10:00:00Z",
             "notes_md": "fixes", "html_url": "javascript:alert(1)", "installable": True,
             "min_upgrade_from": None, "failed_before": True},
            "garbage",
        ],
        "state": "idle",
        "step_log": [{"at": "2026-10-15T10:00:00Z", "state": "preparing", "message": "checking release 1.4.0",
                      "secret": 1}],
        "error": None,
        "operation": {"id": "op1", "kind": "install", "purpose": None, "source": "manual", "from": "1.2.3",
                      "to": "1.4.0", "force": False, "state": "done", "active": False, "result": "success",
                      "started_at": "a", "finished_at": "b", "error": None,
                      "backup_file": "/data/backups/app-1.2.3-20261015.db", "busy": [{"kind": "x", "title": "y"}],
                      "heartbeat_at": "hidden"},
    }
    base.update(over)
    return base


class FakeUpdater:
    """Answers like updater/vf_updater/server.py and records what the app sent."""

    def __init__(self, monkeypatch):
        self.routes: dict = {}
        self.seen: list = []
        real = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "updater.test"
            body = json.loads(request.content) if request.content else None
            self.seen.append((request.method, request.url.path, body, request.headers.get("x-vf-token")))
            answer = self.routes.get((request.method, request.url.path))
            if answer is None:
                return httpx.Response(404, json={"ok": False, "error": "not_found", "message": "no such endpoint"})
            if isinstance(answer, Exception):
                raise answer
            status, payload = answer
            return httpx.Response(status, json=payload)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def fake(monkeypatch):
    return FakeUpdater(monkeypatch)


@pytest.fixture
def token(cfg):
    path = cfg.data_dir / "update"
    path.mkdir(parents=True, exist_ok=True)
    (path / "token").write_text(TOKEN + "\n")
    return TOKEN


@pytest.fixture(autouse=True)
def _no_pause():
    jobs.runner.paused = None
    yield
    jobs.runner.paused = None


def test_status_without_token_is_calm(client, fake):
    res = client.get("/api/updates/status")
    assert res.status_code == 200
    body = res.json()
    assert body["reachable"] is False and body["reason"] == "updater_unavailable"
    assert body["app_version"] == "1.2.3" and body["updater"] is None and body["newest"] is None
    assert fake.seen == []


def test_status_when_updater_is_down(client, fake, token):
    fake.routes[("GET", "/status")] = httpx.ConnectError("refused")
    body = client.get("/api/updates/status").json()
    assert body["reachable"] is False and body["reason"] == "updater_unavailable"


def test_status_on_updater_crash(client, fake, token):
    fake.routes[("GET", "/status")] = (500, {"ok": False, "error": "internal", "message": "boom"})
    body = client.get("/api/updates/status").json()
    assert body["reachable"] is False and body["reason"] == "updater_failed"


def test_status_is_cleaned(client, fake, token):
    fake.routes[("GET", "/status")] = (200, _status())
    res = client.get("/api/updates/status")
    assert res.status_code == 200
    assert TOKEN not in res.text and "updater.test" not in res.text
    body = res.json()
    assert body["reachable"] is True and body["running_jobs"] == [] and body["jobs_paused"] is None
    up = body["updater"]
    assert [r["version"] for r in up["available"]] == ["1.5.0", "1.4.0"]
    assert "extra" not in up["available"][0]
    assert up["available"][0]["notes_md"].startswith("## New")  # raw markdown; the page escapes it
    assert up["available"][1]["html_url"] is None  # only http(s) links pass
    assert up["step_log"] == [{"at": "2026-10-15T10:00:00Z", "state": "preparing",
                               "message": "checking release 1.4.0"}]
    op = up["operation"]
    assert op["backup_file"] == "app-1.2.3-20261015.db" and "heartbeat_at" not in op
    assert op["busy"] == [{"kind": "x", "title": "y"}]
    # newest installable wins over a newer one that needs a step in between
    assert body["newest"] == "1.4.0"
    assert fake.seen[0][3] == TOKEN


def test_status_newest_none_when_nothing_newer(client, fake, token):
    fake.routes[("GET", "/status")] = (200, _status(available=[], operation=None))
    body = client.get("/api/updates/status").json()
    assert body["newest"] is None and body["updater"]["operation"] is None


def test_status_lists_running_jobs(client, fake, token):
    fake.routes[("GET", "/status")] = (200, _status())
    job_id = db.insert("jobs", {"kind": "image.generate", "group_name": "image", "status": "running",
                                "title": "Cat picture", "attempts": 1, "created_at": db.now(),
                                "updated_at": db.now()})
    assert job_id
    body = client.get("/api/updates/status").json()
    assert body["running_jobs"] == [{"kind": "image.generate", "title": "Cat picture"}]


def test_check(client, fake, token):
    fake.routes[("POST", "/check")] = (200, _status(last_check_error="GitHub said 403"))
    res = client.post("/api/updates/check")
    assert res.status_code == 200
    assert res.json()["updater"]["last_check_error"] == "GitHub said 403"
    assert fake.seen[-1][:3] == ("POST", "/check", {})


def test_install_starts(client, fake, token):
    fake.routes[("POST", "/install")] = (202, {"ok": True, "operation": {
        "id": "op2", "kind": "install", "to": "1.4.0", "state": "preparing", "active": True}})
    res = client.post("/api/updates/install", json={"version": "1.4.0"})
    assert res.status_code == 202
    assert res.json()["operation"]["to"] == "1.4.0" and res.json()["operation"]["active"] is True
    assert fake.seen[-1][:3] == ("POST", "/install", {"version": "1.4.0", "force": False})


def test_install_anyway_sends_force(client, fake, token):
    fake.routes[("POST", "/install")] = (202, {"ok": True, "operation": {"id": "op2", "force": True}})
    assert client.post("/api/updates/install", json={"version": "1.4.0", "force": True}).status_code == 202
    assert fake.seen[-1][2] == {"version": "1.4.0", "force": True}


@pytest.mark.parametrize("payload", [{"version": "latest"}, {"version": "1.4"}, {"version": "1.4.0; rm"},
                                     {"version": "1.4.0", "force": "yes"}, {"version": "1.4.0", "x": 1}, {}])
def test_install_rejects_bad_input(client, fake, token, payload):
    res = client.post("/api/updates/install", json=payload)
    assert res.status_code in (400, 422)
    assert fake.seen == []


@pytest.mark.parametrize(("message", "code", "status"), [
    ("updates are turned off in developer mode", "updates_dev_mode", 409),
    ("another update is already running", "update_busy", 409),
    ("version 1.0.0 is not newer than 1.2.3", "update_not_newer", 409),
    ("1.5.0-beta.1 is a test version; switch to the beta channel first", "update_needs_beta", 409),
    ("cannot check releases: GitHub answered HTTP 403", "update_check_failed", 502),
    ("something new", "update_conflict", 409),
])
def test_install_conflicts(client, fake, token, message, code, status):
    fake.routes[("POST", "/install")] = (409, {"ok": False, "error": "conflict", "message": message})
    res = client.post("/api/updates/install", json={"version": "1.4.0"})
    assert res.status_code == status
    err = res.json()["error"]
    assert err["code"] == code and err["message"] == message


def test_install_unknown_release(client, fake, token):
    fake.routes[("POST", "/install")] = (404, {"ok": False, "error": "not_found", "message": "release 9.9.9 not found"})
    res = client.post("/api/updates/install", json={"version": "9.9.9"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "update_not_found"


def test_install_when_token_rejected(client, fake, token):
    fake.routes[("POST", "/install")] = (401, {"ok": False, "error": "unauthorized", "message": "bad token"})
    res = client.post("/api/updates/install", json={"version": "1.4.0"})
    assert res.status_code == 503 and res.json()["error"]["code"] == "updater_unavailable"


def test_settings(client, fake, token):
    fake.routes[("POST", "/settings")] = (200, _status(auto=False, time="04:30", tz="Europe/Kyiv"))
    res = client.post("/api/updates/settings", json={"auto": False, "time": "04:30", "tz": "Europe/Kyiv"})
    assert res.status_code == 200
    up = res.json()["updater"]
    assert up["auto"] is False and up["time"] == "04:30" and up["tz"] == "Europe/Kyiv"
    assert fake.seen[-1][2] == {"auto": False, "time": "04:30", "tz": "Europe/Kyiv"}


def test_settings_sends_only_what_changed(client, fake, token):
    fake.routes[("POST", "/settings")] = (200, _status(channel="beta"))
    client.post("/api/updates/settings", json={"channel": "beta"})
    assert fake.seen[-1][2] == {"channel": "beta"}


@pytest.mark.parametrize("payload", [{}, {"auto": None}, {"auto": "yes"}, {"time": "25:00"}, {"time": "3:00"},
                                     {"channel": "nightly"}, {"tz": ""}, {"color": "red"}])
def test_settings_rejects_bad_input(client, fake, token, payload):
    res = client.post("/api/updates/settings", json=payload)
    assert res.status_code in (400, 422)
    assert fake.seen == []


def test_settings_updater_validation_reaches_page(client, fake, token):
    fake.routes[("POST", "/settings")] = (400, {"ok": False, "error": "bad_request",
                                                "message": "unknown time zone: Mars/Base"})
    res = client.post("/api/updates/settings", json={"tz": "Mars/Base"})
    assert res.status_code == 400
    assert res.json()["error"] == {"code": "update_bad_request", "message": "unknown time zone: Mars/Base",
                                   "details": {}}


def test_stop(client, fake, token):
    fake.routes[("POST", "/stop")] = (202, {"ok": True})
    res = client.post("/api/updates/stop")
    assert res.status_code == 202 and res.json() == {"ok": True}


def test_stop_in_dev_mode(client, fake, token):
    fake.routes[("POST", "/stop")] = (409, {"ok": False, "error": "conflict",
                                            "message": "stopping from here is turned off in developer mode"})
    res = client.post("/api/updates/stop")
    assert res.status_code == 409 and res.json()["error"]["code"] == "updates_dev_mode"


def test_history(client, fake, token):
    fake.routes[("GET", "/history")] = (200, {"items": [
        {"op_id": "op1", "kind": "install", "source": "auto", "version_from": "1.2.3", "version_to": "1.4.0",
         "started_at": "a", "finished_at": "b", "result": "rolled_back", "error": "health check failed",
         "backup_file": "/data/backups/x.db", "other": 1},
        "junk",
    ]})
    res = client.get("/api/updates/history")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["result"] == "rolled_back" and items[0]["backup_file"] == "x.db" and "other" not in items[0]


def test_history_when_updater_is_down(client, fake, token):
    fake.routes[("GET", "/history")] = httpx.ConnectError("refused")
    res = client.get("/api/updates/history")
    assert res.status_code == 503 and res.json()["error"]["code"] == "updater_unavailable"


@pytest.mark.parametrize("path", ["/api/updates/install", "/api/updates/stop", "/api/updates/check",
                                  "/api/updates/settings"])
def test_other_sites_cannot_act(client, fake, token, path):
    res = client.post(path, json={"version": "1.4.0"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden"
    assert fake.seen == []


def test_same_origin_is_allowed(client, fake, token):
    fake.routes[("POST", "/stop")] = (202, {"ok": True})
    assert client.post("/api/updates/stop", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 202
