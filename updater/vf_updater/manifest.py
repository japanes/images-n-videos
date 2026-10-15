"""Validation of the release asset manifest.json.

Shape:
{
  "version": "1.2.0",
  "prerelease": false,
  "images": {"app": "ghcr.io/japanes/images-n-videos/app@sha256:<64 hex>", ...},
  "min_upgrade_from": "1.0.0"          # optional
}
"""

from __future__ import annotations

import re

from . import versions

REQUIRED_IMAGES = ("app", "render", "stt", "updater")
_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestError(ValueError):
    pass


def validate(data, tag_version: str, image_prefix: str) -> dict:
    """Check a manifest and return a normalized copy. Raises ManifestError."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    raw_version = data.get("version")
    if not versions.is_valid(raw_version):
        raise ManifestError(f"bad version in manifest: {raw_version!r}")
    version = versions.normalize(raw_version)
    if version != versions.normalize(tag_version):
        raise ManifestError(f"manifest version {version} does not match release {tag_version}")
    prerelease = data.get("prerelease", versions.is_prerelease(version))
    if not isinstance(prerelease, bool):
        raise ManifestError("prerelease must be true or false")
    if versions.is_prerelease(version) and not prerelease:
        raise ManifestError("a -beta/-rc version must be marked prerelease")
    images = data.get("images")
    if not isinstance(images, dict) or not images:
        raise ManifestError("manifest has no images")
    prefix = image_prefix.rstrip("/")
    normalized = {}
    for key, ref in images.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise ManifestError(f"bad image key: {key!r}")
        if not isinstance(ref, str):
            raise ManifestError(f"image {key} must be a string")
        repo, sep, digest = ref.partition("@")
        if not sep or not _DIGEST_RE.match(digest):
            raise ManifestError(f"image {key} must be pinned by sha256 digest")
        if repo != f"{prefix}/{key}":
            raise ManifestError(f"image {key} must come from {prefix}/{key}, got {repo}")
        normalized[key] = ref
    missing = [k for k in REQUIRED_IMAGES if k not in normalized]
    if missing:
        raise ManifestError("manifest is missing images: " + ", ".join(missing))
    min_from = data.get("min_upgrade_from")
    if min_from in ("", None):
        min_from = None
    elif not versions.is_valid(min_from):
        raise ManifestError(f"bad min_upgrade_from: {min_from!r}")
    else:
        min_from = versions.normalize(min_from)
    return {
        "version": version,
        "prerelease": prerelease,
        "images": normalized,
        "min_upgrade_from": min_from,
    }


def can_upgrade_from(manifest: dict, current_version: str) -> bool:
    min_from = manifest.get("min_upgrade_from")
    if not min_from:
        return True
    try:
        return versions.parse(current_version) >= versions.parse(min_from)
    except versions.VersionError:
        return False
