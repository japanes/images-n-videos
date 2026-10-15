"""Whisper models the service can download.

Each model is pinned to an exact Hugging Face revision and an exact file list with
sizes and digests, so a download is reproducible and verified byte for byte.
The file list mirrors what faster-whisper itself would fetch (config.json,
preprocessor_config.json, model.bin, tokenizer.json, vocabulary.*).

Large files carry the LFS sha256; small files carry the git blob sha1
(``sha1(b"blob <size>\\0" + content)``), which is what the Hub reports for them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFile:
    path: str
    size: int
    sha256: str | None = None
    git_sha1: str | None = None

    def __post_init__(self) -> None:
        if (self.sha256 is None) == (self.git_sha1 is None):
            raise ValueError(f"{self.path}: exactly one of sha256 / git_sha1 is required")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def size_mb(self) -> int:
        """Approximate download size in decimal megabytes (what the UI shows)."""
        return round(self.total_bytes / 1_000_000)


LARGE_V3_TURBO = ModelSpec(
    name="large-v3-turbo",
    # faster-whisper 1.2.1 points "large-v3-turbo" at mobiuslabsgmbh/faster-whisper-large-v3-turbo,
    # which the Hub now redirects here.
    repo="dropbox-dash/faster-whisper-large-v3-turbo",
    revision="0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
    files=(
        ModelFile(
            "preprocessor_config.json", 340, git_sha1="931c77a740890c46365c7ae0c9d350ba3cca908f"
        ),
        ModelFile("config.json", 2263, git_sha1="0351d1d6870005e865747b781b5d7c23ea0459cd"),
        ModelFile("vocabulary.json", 1068114, git_sha1="0adcd01e7c237205d593b707e66dd5d7bc785d2d"),
        ModelFile("tokenizer.json", 2710337, git_sha1="17456db595adc78a973f97d69d8cb50bc87c0b1c"),
        ModelFile(
            "model.bin",
            1617884929,
            sha256="e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
        ),
    ),
)

SMALL = ModelSpec(
    name="small",
    repo="Systran/faster-whisper-small",
    revision="536b0662742c02347bc0e980a01041f333bce120",
    files=(
        ModelFile("config.json", 2370, git_sha1="e5047537059bd8f182d9ca64c470201585015187"),
        ModelFile("vocabulary.txt", 459861, git_sha1="c9074644d9d1205686f16d411564729461324b75"),
        ModelFile("tokenizer.json", 2203239, git_sha1="7818adb6de9fa3064d3ff81226fdd675be1f6344"),
        ModelFile(
            "model.bin",
            483546902,
            sha256="3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        ),
    ),
)

DEFAULT_MODEL = LARGE_V3_TURBO.name

# Order matters: this is the order GET /models returns.
DEFAULT_REGISTRY: dict[str, ModelSpec] = {m.name: m for m in (LARGE_V3_TURBO, SMALL)}
