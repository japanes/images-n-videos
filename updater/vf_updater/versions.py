"""Semantic version parsing and comparison (X.Y.Z with optional -beta.N / -rc.N)."""

from __future__ import annotations

import re
from functools import total_ordering

_VERSION_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)

DEV_VERSION = "0.0.0-dev"


class VersionError(ValueError):
    pass


@total_ordering
class Version:
    """A semver version. Build metadata is ignored, prerelease ranks below release."""

    __slots__ = ("major", "minor", "patch", "pre")

    def __init__(self, major: int, minor: int, patch: int, pre: tuple = ()):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.pre = pre

    @classmethod
    def parse(cls, text: str) -> "Version":
        if not isinstance(text, str):
            raise VersionError(f"version must be a string, got {type(text).__name__}")
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise VersionError(f"not a version: {text!r}")
        pre: tuple = ()
        if match.group(4):
            pre = tuple(int(p) if p.isdigit() else p for p in match.group(4).split("."))
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), pre)

    @property
    def prerelease(self) -> bool:
        return bool(self.pre)

    def _key(self):
        # Release (no prerelease) sorts after any prerelease of the same X.Y.Z.
        # Numeric identifiers sort before alphanumeric ones (semver rule 11).
        pre_key = tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in self.pre)
        return (self.major, self.minor, self.patch, 0 if self.pre else 1, pre_key)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            base += "-" + ".".join(str(p) for p in self.pre)
        return base

    def __repr__(self):
        return f"Version({str(self)!r})"


def parse(text: str) -> Version:
    return Version.parse(text)


def is_valid(text) -> bool:
    try:
        Version.parse(text)
        return True
    except VersionError:
        return False


def normalize(text: str) -> str:
    """'v1.2.3' -> '1.2.3'."""
    return str(Version.parse(text))


def compare(a: str, b: str) -> int:
    va, vb = Version.parse(a), Version.parse(b)
    return (va > vb) - (va < vb)


def is_prerelease(text: str) -> bool:
    return Version.parse(text).prerelease


def channel_allows(channel: str, version: str, prerelease_flag: bool | None = None) -> bool:
    """stable sees only releases; beta sees releases and prereleases."""
    pre = Version.parse(version).prerelease or bool(prerelease_flag)
    if channel == "beta":
        return True
    return not pre
