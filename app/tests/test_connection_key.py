"""Module 01: uploading, replacing and deleting the Google key."""

import json
import logging
import stat

import pytest
from connection_keys import make_key, upload

from vf.core import db, events, models_registry, settings
from vf.core.google import credentials
from vf.core.logs import scrub


def reason(resp):
    assert resp.status_code == 400, resp.text
    body = resp.json()["error"]
    assert body["code"] == "key_invalid"
    return body["details"]["reason"]


def test_upload_valid_key_returns_only_safe_facts(client, cfg):
    resp = upload(client, make_key())
    assert resp.status_code == 200, resp.text
    assert "PRIVATE KEY" not in resp.text and "SECRETBODY" not in resp.text
    assert "0123456789abcdef0123456789abcdef" not in resp.text  # never the full key id
    key = resp.json()["key"]
    assert key["project_id"] == "demo-project-123"
    assert key["client_email"] == "vertex@demo-project-123.iam.gserviceaccount.com"
    assert key["key_id_tail"] == "KEYID9"
    assert key["uploaded_at"]

    path = cfg.secrets_dir / credentials.KEY_NAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert client.get("/api/meta").json()["has_key"] is True
    row = db.fetch_one("SELECT * FROM google_credentials")
    assert row["project_id"] == "demo-project-123"

    state = client.get("/api/connection").json()
    assert "PRIVATE KEY" not in json.dumps(state)
    assert state["key"]["project_id"] == "demo-project-123"


@pytest.mark.parametrize("payload, expected", [
    ({"installed": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s"}}, "oauth_client"),
    ({"web": {"client_id": "x.apps.googleusercontent.com"}}, "oauth_client"),
    (b'{"type": "service_account", "project_id": "p", "private_key": "-----BEGIN PRI', "not_json"),
    (b"\x89PNG\r\n\x1a\nnot json at all", "not_json"),
    (b"[1, 2, 3]", "not_json"),
    (b"   ", "empty"),
    ({"type": "authorized_user", "client_id": "x", "refresh_token": "y"}, "not_service_account"),
    (make_key(private_key_id=None), "missing_fields"),
    (make_key(private_key="not a pem"), "bad_private_key"),
    (b"{" + b" " * (70 * 1024) + b"}", "too_large"),
])
def test_bad_files_are_rejected_with_a_reason(client, cfg, payload, expected):
    assert reason(upload(client, payload)) == expected
    assert not (cfg.secrets_dir / credentials.KEY_NAME).exists()
    assert client.get("/api/meta").json()["has_key"] is False


def test_missing_key_id_names_the_field(client):
    details = upload(client, make_key(private_key_id=None)).json()["error"]["details"]
    assert details["fields"] == ["private_key_id"]


def test_replace_key_without_restart(client, monkeypatch):
    published = []
    real = events.publish
    monkeypatch.setattr(events, "publish", lambda t, p=None: (published.append(t), real(t, p)))

    assert upload(client, make_key()).status_code == 200
    client.put("/api/connection", json={"key_ban_restored": True})
    first_model = models_registry.list_models("text")[0]["id"]
    models_registry.set_availability({first_model: False})

    resp = upload(client, make_key(project="other-project-9", key_id="ffff00001111"))
    assert resp.status_code == 200
    state = resp.json()
    assert state["key"]["project_id"] == "other-project-9"
    assert state["key"]["key_id_tail"] == "001111"
    assert state["key_ban_restored"] is False          # a new key needs the ban lifted again
    assert state["checks"]["text"] is None              # old results belong to the old key
    assert models_registry.get(first_model)["available"] is None  # new project, not checked yet
    assert credentials.project_id() == "other-project-9"
    assert published.count("connection.updated") >= 2
    assert db.fetch_value("SELECT COUNT(*) FROM google_credentials") == 1


def test_delete_key(client, cfg):
    upload(client, make_key())
    resp = client.delete("/api/connection/key")
    assert resp.status_code == 200
    assert resp.json()["key"] is None
    assert not (cfg.secrets_dir / credentials.KEY_NAME).exists()
    assert client.get("/api/meta").json()["has_key"] is False
    assert db.fetch_value("SELECT COUNT(*) FROM google_credentials") == 0


def test_key_put_by_hand_gets_a_row(client, cfg):
    credentials.save_key(json.dumps(make_key(project="by-hand-1")))
    state = client.get("/api/connection").json()
    assert state["key"]["project_id"] == "by-hand-1"
    assert db.fetch_value("SELECT project_id FROM google_credentials") == "by-hand-1"


def test_key_never_reaches_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    upload(client, make_key())
    client.post("/api/connection/check")
    upload(client, make_key(private_key="broken"))
    upload(client, b'{"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\\nSECRETBODY')
    client.delete("/api/connection/key")
    text = caplog.text + "".join(str(r.args) for r in caplog.records)
    assert "SECRETBODY" not in text
    assert "PRIVATE KEY" not in text
    assert "0123456789abcdef0123456789abcdef" not in text


def test_scrub_hides_a_whole_key_file():
    raw = json.dumps(make_key())
    cleaned = scrub(f"uploaded {raw}")
    assert "SECRETBODY" not in cleaned
    assert "0123456789abcdef0123456789abcdef" not in cleaned


def test_trial_date_and_ban_mark(client):
    resp = client.put("/api/connection", json={"trial_started_on": "2026-09-14"})
    assert resp.status_code == 200, resp.text
    trial = resp.json()["trial"]
    assert trial["started_on"] == "2026-09-14"
    assert trial["ends_on"] == "2026-12-13"
    assert isinstance(trial["days_left"], int)
    assert settings.get("connection.trial_started_on") == "2026-09-14"

    for bad in ("2026-13-01", "14.09.2026", "2999-01-01", 12):
        r = client.put("/api/connection", json={"trial_started_on": bad})
        assert r.status_code == 400, bad
        assert r.json()["error"]["code"] == "validation"
    assert settings.get("connection.trial_started_on") == "2026-09-14"

    cleared = client.put("/api/connection", json={"trial_started_on": None}).json()
    assert cleared["trial"]["started_on"] is None
    assert settings.get("connection.trial_started_on") is None

    assert client.put("/api/connection", json={"key_ban_restored": True}).json()["key_ban_restored"] is True


def test_connection_settings_stay_off_the_generic_settings_api(client):
    body = client.get("/api/settings").json()
    keys = set(body["values"]) | {item["key"] for item in body["items"]}
    assert not any(k.startswith("connection.") for k in keys)

    # The date is checked only by PUT /api/connection; the generic endpoint refuses it.
    resp = client.put("/api/settings", json={"connection.trial_started_on": "garbage"})
    assert resp.status_code == 400
    assert settings.get("connection.trial_started_on") is None
