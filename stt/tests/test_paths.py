from __future__ import annotations

import os

import pytest

from stt.errors import ServiceError
from stt.paths import resolve_input


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "data"
    (root / "files" / "sub").mkdir(parents=True)
    (root / "files" / "sub" / "a.wav").write_bytes(b"x")
    (root / "secrets").mkdir()
    (root / "secrets" / "key.json").write_text("{}")
    (root / "models" / "small").mkdir(parents=True)
    (root / "models" / "small" / "model.bin").write_bytes(b"x")
    (tmp_path / "outside.wav").write_bytes(b"x")
    return root


def code_of(data_dir, raw) -> str:
    with pytest.raises(ServiceError) as exc:
        resolve_input(data_dir, raw)
    return exc.value.code


def test_relative_file(data_dir):
    path = resolve_input(data_dir, "files/sub/a.wav")
    assert path == (data_dir / "files" / "sub" / "a.wav").resolve()
    assert resolve_input(data_dir, "./files/sub/a.wav") == path


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        5,
        "/etc/passwd",
        "\\\\server\\share\\a.wav",
        "C:\\a.wav",
        "c:/a.wav",
        "../outside.wav",
        "files/../../outside.wav",
        "files/sub/../../secrets/key.json",
        "secrets/key.json",
        "models/small/model.bin",
        "files/a\x00.wav",
    ],
)
def test_rejected(data_dir, raw):
    assert code_of(data_dir, raw) == "bad_request"


def test_symlink_escape_is_rejected(data_dir, tmp_path):
    os.symlink(tmp_path / "outside.wav", data_dir / "files" / "link.wav")
    assert code_of(data_dir, "files/link.wav") == "bad_request"
    os.symlink(data_dir / "secrets", data_dir / "files" / "keys")
    assert code_of(data_dir, "files/keys/key.json") == "bad_request"


def test_symlink_inside_is_allowed(data_dir):
    os.symlink(data_dir / "files" / "sub" / "a.wav", data_dir / "files" / "b.wav")
    assert resolve_input(data_dir, "files/b.wav") == (data_dir / "files/sub/a.wav").resolve()


@pytest.mark.parametrize("raw", ["files/missing.wav", "files/sub", "files"])
def test_not_found(data_dir, raw):
    assert code_of(data_dir, raw) == "not_found"


def test_data_dir_itself(data_dir):
    assert code_of(data_dir, ".") == "not_found"
