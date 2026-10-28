import os

os.environ.setdefault("VF_GOOGLE_MODE", "stub")
os.environ["VF_STUB_DELAY"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vf.core import db, migrations, models_registry  # noqa: E402
from vf.core.config import DEFAULT_HOSTS, Config, set_config  # noqa: E402
from vf.core.google import gateway  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    config = Config(data_dir=tmp_path / "data", version="1.2.3", google_mode="stub",
                    render_url="http://render.test", stt_url="http://stt.test",
                    allowed_hosts=DEFAULT_HOSTS + ("testserver", "test"))
    config.data_dir.mkdir(parents=True)
    set_config(config)
    yield config


@pytest.fixture
def database(cfg):
    database = db.init(cfg.db_path)
    migrations.apply_all(database)
    models_registry.seed()
    yield database
    db.close()


@pytest.fixture
def no_sleep(monkeypatch):
    """Retries and refusal pauses return at once; the pauses asked for are recorded."""
    pauses: list[float] = []

    async def fake_sleep(seconds, cancel=None):
        pauses.append(seconds)
        if cancel and cancel():
            raise gateway.GoogleCallError("cancelled", "cancelled")

    monkeypatch.setattr(gateway, "_sleep", fake_sleep)
    return pauses


@pytest.fixture
def client(cfg):
    from vf.main import create_app

    app = create_app(cfg)
    with TestClient(app) as test_client:
        yield test_client
