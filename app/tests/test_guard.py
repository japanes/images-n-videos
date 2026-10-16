import pytest

from vf.core.config import DEFAULT_HOSTS
from vf.core.guard import host_name, refusal

ALLOWED = frozenset(DEFAULT_HOSTS)


@pytest.mark.parametrize("value, name", [
    ("127.0.0.1:8787", "127.0.0.1"),
    ("LOCALHOST", "localhost"),
    ("[::1]:8787", "::1"),
    ("::1", "::1"),
    ("app:8787", "app"),
])
def test_host_name(value, name):
    assert host_name(value) == name


@pytest.mark.parametrize("headers", [
    {"host": "127.0.0.1:8787"},
    {"host": "localhost:8787", "sec-fetch-site": "same-origin"},
    {"host": "localhost:3000", "sec-fetch-site": "same-origin", "origin": "http://localhost:3000"},
    {"host": "app:8787"},  # the updater inside the compose network
    {"host": "127.0.0.1:8787", "origin": "http://localhost:8787"},
    {"host": "127.0.0.1:8787", "sec-fetch-site": "none"},  # typed in the address bar
])
def test_own_page_and_local_tools_pass(headers):
    assert refusal("POST", headers, ALLOWED) is None


@pytest.mark.parametrize("headers", [
    {"host": "127.0.0.1:8787", "sec-fetch-site": "cross-site"},
    {"host": "127.0.0.1:8787", "sec-fetch-site": "same-site"},
    {"host": "127.0.0.1:8787", "origin": "https://evil.example"},
    {"host": "127.0.0.1:8787", "origin": "null"},
])
def test_writes_from_other_sites_are_refused(headers):
    assert refusal("POST", headers, ALLOWED) == "cross_site"
    assert refusal("DELETE", headers, ALLOWED) == "cross_site"


def test_reads_from_other_sites_pass_but_foreign_hosts_do_not():
    # a cross-site GET cannot read the answer without CORS; a rebinding name can, so the host decides
    assert refusal("GET", {"host": "127.0.0.1:8787", "sec-fetch-site": "cross-site"}, ALLOWED) is None
    assert refusal("GET", {"host": "rebind.evil.example:8787"}, ALLOWED) == "host"
    assert refusal("POST", {"host": "rebind.evil.example", "sec-fetch-site": "same-origin"}, ALLOWED) == "host"


def test_app_refuses_a_cross_site_post(client):
    res = client.post("/api/chat/chats", json={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"
    assert client.post("/api/chat/chats", json={}, headers={"Sec-Fetch-Site": "same-origin"}).status_code < 400


def test_app_refuses_a_foreign_host(client):
    res = client.get("/health", headers={"Host": "rebind.evil.example"})
    assert res.status_code == 403
    assert res.json()["error"]["details"]["reason"] == "host"
    assert client.get("/health", headers={"Host": "localhost:8787"}).status_code == 200


def test_extra_hosts_come_from_the_environment(monkeypatch):
    from vf.core.config import load_config

    monkeypatch.setenv("VF_ALLOWED_HOSTS", " my-box.local , ")
    assert load_config().allowed_hosts == DEFAULT_HOSTS + ("my-box.local",)
