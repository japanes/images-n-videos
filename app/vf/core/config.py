"""Process configuration from the environment. Read once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    version: str = "0.0.0-dev"
    # "live" talks to Google; "stub" fakes every Google call (tests, demos, CI).
    google_mode: str = "live"
    render_url: str = "http://render:3000"
    stt_url: str = "http://stt:8000"
    updater_url: str = "http://updater:8080"
    web_dir: Path | None = None
    repo: str = "japanes/images-n-videos"
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "cache" / "tmp"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def stub(self) -> bool:
        return self.google_mode == "stub"


def load_config() -> Config:
    env = os.environ
    web_dir = env.get("VF_WEB_DIR")
    return Config(
        data_dir=Path(env.get("VF_DATA_DIR", "/data")),
        version=env.get("VF_VERSION", "0.0.0-dev"),
        google_mode=env.get("VF_GOOGLE_MODE", "live").strip().lower() or "live",
        render_url=env.get("VF_RENDER_URL", "http://render:3000").rstrip("/"),
        stt_url=env.get("VF_STT_URL", "http://stt:8000").rstrip("/"),
        updater_url=env.get("VF_UPDATER_URL", "http://updater:8080").rstrip("/"),
        web_dir=Path(web_dir) if web_dir else None,
        repo=env.get("VF_REPO", "japanes/images-n-videos"),
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: Config) -> None:
    global _config
    _config = config


def override(**changes) -> Config:
    """Replace fields of the active config (tests)."""
    cfg = replace(get_config(), **changes)
    set_config(cfg)
    return cfg
