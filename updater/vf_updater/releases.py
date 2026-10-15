"""GitHub Releases client (unauthenticated) with caching and rate-limit care.

The list is cached in /data/update/check.json together with the ETag, so a
repeated check usually costs a 304 that GitHub does not count against the
60 requests/hour limit.
"""

from __future__ import annotations

import time

from . import manifest as manifest_mod
from . import versions
from .http_util import HttpError, request
from .store import utc_now

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
MIN_MANUAL_INTERVAL = 60  # seconds between API calls made on demand
MAX_NOTES = 20000


class ReleaseError(Exception):
    pass


def _normalize_release(raw: dict):
    if not isinstance(raw, dict) or raw.get("draft"):
        return None
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not versions.is_valid(tag):
        return None
    version = versions.normalize(tag)
    manifest_url = None
    for asset in raw.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == "manifest.json":
            manifest_url = asset.get("browser_download_url")
            break
    notes = raw.get("body") or ""
    if not isinstance(notes, str):
        notes = ""
    return {
        "version": version,
        "tag": tag,
        "prerelease": bool(raw.get("prerelease")) or versions.is_prerelease(version),
        "published_at": raw.get("published_at"),
        "notes_md": notes[:MAX_NOTES],
        "html_url": raw.get("html_url"),
        "manifest_url": manifest_url,
    }


def filter_available(releases: list, current_version: str, channel: str) -> list:
    """Releases newer than current_version allowed by the channel, newest first."""
    try:
        current = versions.parse(current_version)
    except versions.VersionError:
        current = versions.parse(versions.DEV_VERSION)
    result = []
    for rel in releases or []:
        try:
            ver = versions.parse(rel["version"])
        except (KeyError, versions.VersionError):
            continue
        if ver <= current:
            continue
        if not versions.channel_allows(channel, rel["version"], rel.get("prerelease")):
            continue
        result.append(rel)
    result.sort(key=lambda r: versions.parse(r["version"]), reverse=True)
    return result


class ReleaseClient:
    def __init__(self, cfg, store, http=request, clock=time.time):
        self.cfg = cfg
        self.store = store
        self.http = http
        self.clock = clock

    def cached(self) -> dict:
        return self.store.read_check()

    def releases(self) -> list:
        return self.cached().get("releases") or []

    def find(self, version: str):
        for rel in self.releases():
            if rel.get("version") == version:
                return rel
        return None

    def fetch(self, manual: bool = False) -> list:
        """Refresh the release list. Errors are stored in check.json and re-raised."""
        cache = self.cached()
        now = self.clock()
        limited_until = cache.get("rate_limited_until") or 0
        if now < limited_until:
            wait_min = int((limited_until - now) // 60) + 1
            raise ReleaseError(f"GitHub rate limit reached, next try in about {wait_min} min")
        last_call = cache.get("last_api_call") or 0
        if manual and now - last_call < MIN_MANUAL_INTERVAL and cache.get("releases") is not None \
                and not cache.get("last_check_error"):
            return cache.get("releases") or []
        headers = dict(API_HEADERS)
        if cache.get("etag") and cache.get("releases") is not None:
            headers["If-None-Match"] = cache["etag"]
        cache["last_api_call"] = now
        try:
            resp = self.http("GET", f"{self.cfg.releases_url}?per_page=30", headers=headers,
                             timeout=20)
        except HttpError as exc:
            return self._fail(cache, f"cannot reach GitHub: {exc}")
        if resp.status in (403, 429) and (
            resp.header("x-ratelimit-remaining") == "0" or resp.status == 429
        ):
            reset = resp.header("x-ratelimit-reset")
            retry_after = resp.header("retry-after")
            try:
                until = float(reset) if reset else now + float(retry_after or 3600)
            except ValueError:
                until = now + 3600
            cache["rate_limited_until"] = max(until, now + 60)
            return self._fail(cache, "GitHub rate limit reached, will try later")
        if resp.status == 304:
            releases = cache.get("releases") or []
        elif resp.status == 200:
            try:
                raw = resp.json()
            except ValueError:
                return self._fail(cache, "GitHub returned invalid JSON")
            if not isinstance(raw, list):
                return self._fail(cache, "GitHub returned an unexpected answer")
            releases = [r for r in (_normalize_release(x) for x in raw) if r]
            cache["releases"] = releases
            cache["etag"] = resp.header("etag")
        else:
            return self._fail(cache, f"GitHub answered HTTP {resp.status}")
        cache["rate_limited_until"] = 0
        cache["last_check_at"] = utc_now()
        cache["last_check_error"] = None
        self.store.write_check(cache)
        return releases

    def _fail(self, cache: dict, message: str):
        cache["last_check_at"] = utc_now()
        cache["last_check_error"] = message
        self.store.write_check(cache)
        raise ReleaseError(message)

    def fetch_tag(self, version: str):
        """Look up one release by tag (used for the version we were shipped with)."""
        rel = self.find(version)
        if rel:
            return rel
        try:
            resp = self.http("GET", f"{self.cfg.releases_url}/tags/v{version}",
                             headers=dict(API_HEADERS), timeout=20)
        except HttpError as exc:
            raise ReleaseError(f"cannot reach GitHub: {exc}") from None
        if resp.status != 200:
            raise ReleaseError(f"release v{version}: HTTP {resp.status}")
        try:
            rel = _normalize_release(resp.json())
        except ValueError:
            rel = None
        if not rel:
            raise ReleaseError(f"release v{version} is not usable")
        return rel

    def get_manifest(self, rel: dict) -> dict:
        """Download and validate manifest.json of a release (cached per version)."""
        version = rel["version"]
        cache = self.cached()
        manifests = cache.get("manifests") or {}
        if isinstance(manifests.get(version), dict):
            try:
                return manifest_mod.validate(manifests[version], version, self.cfg.image_prefix)
            except manifest_mod.ManifestError:
                pass
        url = rel.get("manifest_url")
        if not url:
            raise ReleaseError(f"release {version} has no manifest.json")
        try:
            resp = self.http("GET", url, headers={"Accept": "application/octet-stream"},
                             timeout=30, max_bytes=256 * 1024)
        except HttpError as exc:
            raise ReleaseError(f"cannot download manifest: {exc}") from None
        if resp.status != 200:
            raise ReleaseError(f"manifest download failed: HTTP {resp.status}")
        try:
            data = resp.json()
        except ValueError:
            raise ReleaseError("manifest.json is not valid JSON") from None
        try:
            result = manifest_mod.validate(data, version, self.cfg.image_prefix)
        except manifest_mod.ManifestError as exc:
            raise ReleaseError(f"bad manifest: {exc}") from None
        cache = self.cached()
        manifests = cache.get("manifests") or {}
        manifests[version] = result
        # Keep only manifests of releases we still know about.
        known = {r.get("version") for r in cache.get("releases") or []} | {version}
        cache["manifests"] = {k: v for k, v in manifests.items() if k in known}
        self.store.write_check(cache)
        return result
