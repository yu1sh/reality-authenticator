import hashlib
from pathlib import Path

import pytest

from reality_core import sha256_bytes, sha256_file


def test_sha256_bytes_matches_known_vector() -> None:
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_empty_file_hash_matches_known_vector(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.write_bytes(b"")

    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()


def test_file_hash_is_repeatable_with_small_chunks(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"reality-authenticator" * 100)

    assert sha256_file(path, chunk_size=7) == sha256_file(path)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "missing.bin")


def test_invalid_chunk_size_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"data")

    with pytest.raises(ValueError):
        sha256_file(path, chunk_size=0)
