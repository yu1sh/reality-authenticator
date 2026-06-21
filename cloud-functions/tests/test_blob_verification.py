import hashlib

import pytest

from reality_cloud.blob_verification import BlobVerificationError, verify_blob


class Downloader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def chunks(self):
        return iter(self._chunks)


class Blob:
    def __init__(self, data: bytes, *, content_type: str = "image/jpeg") -> None:
        self.data = data
        self.content_type = content_type

    def get_blob_properties(self):
        return {
            "size": len(self.data),
            "content_settings": {"content_type": self.content_type},
        }

    def download_blob(self):
        return Downloader([self.data[:2], self.data[2:]])


class Container:
    def __init__(self, blob: Blob) -> None:
        self.blob = blob

    def get_blob_client(self, path: str):
        assert path == "evidence/session-1/image.jpg"
        return self.blob


def metadata(data: bytes) -> dict[str, object]:
    return {
        "blob_path": "evidence/session-1/image.jpg",
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": "image/jpeg",
        "size_bytes": len(data),
    }


def test_blob_verification_hashes_chunks() -> None:
    data = b"jpeg-data"
    verify_blob(Container(Blob(data)), metadata(data))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("size_bytes", 1, "ERR_HASH_MISMATCH"),
        ("content_type", "audio/wav", "ERR_HASH_MISMATCH"),
        ("sha256", "0" * 64, "ERR_HASH_MISMATCH"),
    ],
)
def test_blob_verification_rejects_mismatch(
    field: str, value: object, code: str
) -> None:
    data = b"jpeg-data"
    changed = metadata(data)
    changed[field] = value
    with pytest.raises(BlobVerificationError) as caught:
        verify_blob(Container(Blob(data)), changed)
    assert caught.value.code == code


def test_missing_blob_uses_public_file_missing_code() -> None:
    class ResourceNotFoundError(Exception):
        pass

    class MissingBlob(Blob):
        def get_blob_properties(self):
            raise ResourceNotFoundError

    data = b"jpeg-data"
    with pytest.raises(BlobVerificationError) as caught:
        verify_blob(Container(MissingBlob(data)), metadata(data))

    assert caught.value.code == "ERR_FILE_MISSING"
