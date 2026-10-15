"""Updater configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import versions

DEFAULT_PREFIX = "ghcr.io/japanes/images-n-videos"
DEFAULT_REPO = "japanes/images-n-videos"
DEFAULT_PROJECT = "vertexai-factory"
DEFAULT_VOLUME = "vertexai-factory-data"

# Services pulled and switched on every update. The updater goes last on purpose.
SERVICES = ("app", "render", "stt", "updater")

# Environment variables forwarded to the helper container and the stack compose.
PASSTHROUGH_ENV = (
    "VF_PORT",
    "VF_PROJECT",
    "VF_DATA_VOLUME",
    "VF_IMAGE_PREFIX",
    "VF_REPO",
    "VF_RELEASES_API",
    "VF_GOOGLE_MODE",
    "VF_VERIFY_TIMEOUT",
    "VF_UPDATER_DEV",
    "TZ",
)


def _int(env, name, default):
    try:
        return int(env.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    version: str = versions.DEV_VERSION
    data_dir: str = "/data"
    project: str = DEFAULT_PROJECT
    data_volume: str = DEFAULT_VOLUME
    image_prefix: str = DEFAULT_PREFIX
    repo: str = DEFAULT_REPO
    releases_api: str = ""
    stack_file: str = "/stack/compose.yml"
    app_url: str = "http://app:8787"
    updater_url: str = "http://updater:8080"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    dev: bool = False
    verify_timeout: int = 120
    prepare_timeout: int = 600
    check_interval: int = 6 * 3600
    docker_socket: str = "/var/run/docker.sock"
    env: dict = field(default_factory=dict)

    @property
    def releases_url(self) -> str:
        if self.releases_api:
            return self.releases_api.rstrip("/")
        return f"https://api.github.com/repos/{self.repo}/releases"

    @property
    def network(self) -> str:
        return f"{self.project}_default"

    @property
    def helper_name(self) -> str:
        return f"{self.project}-update-helper"

    def image(self, service: str, version: str) -> str:
        return f"{self.image_prefix}/{service}:{version}"

    def passthrough_env(self) -> dict:
        return {k: self.env[k] for k in PASSTHROUGH_ENV if self.env.get(k)}


def load(env=None) -> Config:
    env = dict(os.environ if env is None else env)
    version = env.get("VF_VERSION") or versions.DEV_VERSION
    if not versions.is_valid(version):
        version = versions.DEV_VERSION
    return Config(
        version=versions.normalize(version),
        data_dir=env.get("VF_DATA_DIR", "/data"),
        project=env.get("VF_PROJECT") or DEFAULT_PROJECT,
        data_volume=env.get("VF_DATA_VOLUME") or DEFAULT_VOLUME,
        image_prefix=(env.get("VF_IMAGE_PREFIX") or DEFAULT_PREFIX).rstrip("/"),
        repo=env.get("VF_REPO") or DEFAULT_REPO,
        releases_api=env.get("VF_RELEASES_API", ""),
        stack_file=env.get("VF_STACK_FILE", "/stack/compose.yml"),
        app_url=(env.get("VF_APP_URL") or "http://app:8787").rstrip("/"),
        updater_url=(env.get("VF_SELF_URL") or "http://updater:8080").rstrip("/"),
        listen_port=_int(env, "VF_UPDATER_PORT", 8080),
        dev=env.get("VF_UPDATER_DEV", "") in ("1", "true", "yes"),
        verify_timeout=_int(env, "VF_VERIFY_TIMEOUT", 120),
        prepare_timeout=_int(env, "VF_PREPARE_TIMEOUT", 600),
        check_interval=_int(env, "VF_CHECK_INTERVAL", 6 * 3600),
        env=env,
    )
