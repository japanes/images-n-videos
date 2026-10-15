import logging

import pytest

from vf.core import db, files, migrations, settings
from vf.core.errors import AppError
from vf.core.logs import ScrubFilter, scrub


def test_migrations_are_idempotent(database):
    assert migrations.apply_all(database) == []
    names = {r["name"] for r in db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"settings", "files", "jobs", "ai_calls", "ai_call_refs", "models", "role_models"} <= names


def test_json_columns_round_trip(database):
    job_id = db.insert("jobs", {"kind": "x", "group_name": "default", "status": "queued",
                                "payload_json": {"a": [1, 2]}, "created_at": db.now(), "updated_at": db.now()})
    assert db.get("jobs", job_id)["payload_json"] == {"a": [1, 2]}


def test_nested_transactions_roll_back_inner_only(database):
    with db.tx():
        db.insert("settings", {"key": "a", "value_json": 1, "updated_at": db.now()})
        with pytest.raises(RuntimeError), db.tx():
            db.insert("settings", {"key": "b", "value_json": 2, "updated_at": db.now()})
            raise RuntimeError
    keys = {r["key"] for r in db.fetch_all("SELECT key FROM settings")}
    assert keys == {"a"}


def test_settings_validation(database):
    settings.define("test.count", 3, min=1, max=5)
    settings.define("test.mode", "a", kind="enum", choices=["a", "b"])
    assert settings.get("test.count") == 3
    assert settings.set("test.count", "4") == 4
    assert settings.get("test.count") == 4
    with pytest.raises(AppError):
        settings.set("test.count", 9)
    with pytest.raises(AppError):
        settings.set("test.mode", "c")
    with pytest.raises(AppError):
        settings.set("test.nope", 1)
    settings.reset("test.count")
    assert settings.get("test.count") == 3


def test_scrub_hides_keys_and_tokens():
    text = ('{"private_key_id": "abc123", "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIE\\n'
            '-----END PRIVATE KEY-----\\n"} Authorization: Bearer ya29.a0AfH6SMB')
    clean = scrub(text)
    assert "abc123" not in clean
    assert "MIIE" not in clean
    assert "a0AfH6SMB" not in clean


def test_scrub_filter_on_records(caplog):
    logger = logging.getLogger("vf.test.scrub")
    logger.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO, logger="vf.test.scrub"):
        logger.info("token %s", "ya29.secretsecret")
    assert "secretsecret" not in caplog.text


def test_files_save_and_refuse_escape(database):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (40, 20), "red").save(buf, "PNG")
    row = files.save_bytes(buf.getvalue(), name="red.png", origin="upload")
    assert row["kind"] == "image" and row["width"] == 40 and row["height"] == 20
    assert files.path_of(row).read_bytes() == buf.getvalue()
    assert files.public(row)["url"] == f"/files/{row['id']}"
    with pytest.raises(AppError):
        files.abs_path("../../etc/passwd")


def test_file_in_use_is_kept(database):
    row = files.save_bytes(b"hello", mime="text/plain")

    @files.usage_provider
    def _uses(file_id):
        return [{"type": "test", "id": 1}] if file_id == row["id"] else []

    try:
        with pytest.raises(AppError) as err:
            files.delete(row["id"])
        assert err.value.code == "file_in_use"
        files.delete(row["id"], force=True)
        assert db.get("files", row["id"]) is None
    finally:
        files._usage_providers.remove(_uses)
