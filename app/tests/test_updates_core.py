"""App side of updates in the core: the pause lease the updater takes, and a quick shutdown."""

import signal
import socket
import threading
import time

import httpx
import pytest

from vf.core import events, jobs

TOKEN = "updater-secret-token-123"


@pytest.fixture(autouse=True)
def _no_pause():
    jobs.runner.paused = None
    yield
    jobs.runner.paused = None


@pytest.fixture
def token(cfg):
    path = cfg.data_dir / "update"
    path.mkdir(parents=True, exist_ok=True)
    (path / "token").write_text(TOKEN)
    return TOKEN


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(jobs.time, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def published(monkeypatch):
    seen: list = []
    monkeypatch.setattr(events, "publish", lambda event_type, payload=None: seen.append((event_type, payload)))
    return seen


def test_pause_with_ttl_lifts_itself(database, clock, published):
    jobs.pause_new("update", ttl_seconds=60, target="1.4.0")
    assert jobs.runner.paused == "update" and jobs.runner.paused_target == "1.4.0"
    clock[0] += 59
    jobs.runner.dispatch()
    assert jobs.runner.paused == "update"
    assert published == [("jobs.paused", {"reason": "update"})]
    clock[0] += 2
    assert jobs.runner.paused is None  # reads as lifted even before the loop notices
    jobs.runner.dispatch()
    assert published[-1] == ("jobs.paused", {"reason": None})
    assert jobs.runner.paused_until is None and jobs.runner.paused_target is None
    jobs.runner.dispatch()
    assert len(published) == 2  # lifted once


def test_repeated_prepare_extends_the_pause(database, clock, published):
    jobs.pause_new("update", ttl_seconds=60)
    clock[0] += 50
    jobs.pause_new("update", ttl_seconds=60)
    clock[0] += 50
    assert jobs.runner.paused == "update"


def test_pause_without_ttl_stays(database, clock, published):
    jobs.pause_new("update")
    clock[0] += 10**7
    jobs.runner.dispatch()
    assert jobs.runner.paused == "update"


def test_resume_clears_the_lease(database, clock, published):
    jobs.pause_new("update", ttl_seconds=60, target="1.4.0")
    jobs.resume_new()
    assert jobs.runner.paused is None and jobs.runner.paused_until is None and jobs.runner.paused_target is None


@pytest.mark.parametrize(("ttl", "expected"), [
    (90, 90), (5, 30), (10**9, 6 * 3600), ("abc", 1800), (None, 1800), (True, 1800), (-1, 1800), (0, 1800),
])
def test_prepare_takes_ttl_and_target(client, token, ttl, expected):
    before = time.monotonic()
    res = client.post("/api/internal/updates/prepare", headers={"X-VF-Token": token},
                      json={"target_version": "1.4.0", "ttl_seconds": ttl})
    assert res.status_code == 200 and res.json() == {"ok": True, "busy": []}
    assert jobs.runner.paused == "update" and jobs.runner.paused_target == "1.4.0"
    assert jobs.runner.paused_until == pytest.approx(before + expected, abs=5)


def test_prepare_without_body_uses_default_ttl(client, token):
    before = time.monotonic()
    assert client.post("/api/internal/updates/prepare", headers={"X-VF-Token": token}).json()["ok"] is True
    assert jobs.runner.paused_until == pytest.approx(before + 1800, abs=5)
    assert jobs.runner.paused_target is None


def test_prepare_ignores_odd_target(client, token):
    client.post("/api/internal/updates/prepare", headers={"X-VF-Token": token}, json={"target_version": 5})
    assert jobs.runner.paused_target is None
    client.post("/api/internal/updates/prepare", headers={"X-VF-Token": token},
                json={"target_version": "9" * 500})
    assert len(jobs.runner.paused_target) == 64


def test_prepare_still_needs_token(client):
    assert client.post("/api/internal/updates/prepare", json={"ttl_seconds": 60}).status_code == 403
    assert jobs.runner.paused is None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_stop_signal_ends_open_event_streams(cfg):
    """An open browser tab must not hold the shutdown for the 10 s graceful timeout."""
    from vf.main import create_app, make_server

    port = _free_port()
    server = make_server(create_app(cfg), host="127.0.0.1", port=port)
    thread = threading.Thread(target=server.run, name="test-server", daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as http:
            with http.stream("GET", "/api/events") as res:
                assert res.status_code == 200
                assert next(res.iter_lines()).startswith("retry:")
                started = time.monotonic()
                server.handle_exit(signal.SIGTERM, None)
                thread.join(timeout=9)
                elapsed = time.monotonic() - started
        assert not thread.is_alive()
        assert elapsed < 5, f"shutdown took {elapsed:.1f} s"
        assert not jobs.runner.alive()
    finally:
        server.should_exit = True
        thread.join(timeout=12)
        events._closing = False
