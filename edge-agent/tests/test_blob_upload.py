import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from reality_edge.blob_upload import BlobUploadError, upload_evidence_files


class Response:
    def close(self) -> None:
        pass


def bundle(tmp_path: Path) -> Path:
    (tmp_path / "image.jpg").write_bytes(b"image")
    (tmp_path / "audio.wav").write_bytes(b"audio")
    manifest = {
        "files": {
            "image": {
                "blob_path": "evidence/session-1/image.jpg",
                "content_type": "image/jpeg",
            },
            "audio": {
                "blob_path": "evidence/session-1/audio.wav",
                "content_type": "audio/x-wav",
            },
        }
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def targets() -> dict[str, object]:
    return {
        "mode": "sas_url",
        "image": {
            "blob_path": "evidence/session-1/image.jpg",
            "url": "https://storage/image?secret",
            "content_type": "image/jpeg",
        },
        "audio": {
            "blob_path": "evidence/session-1/audio.wav",
            "url": "https://storage/audio?secret",
            "content_type": "audio/wav",
        },
    }


def test_upload_uses_block_blob_headers(tmp_path: Path) -> None:
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return Response()

    upload_evidence_files(
        upload=targets(), manifest_path=bundle(tmp_path), opener=opener
    )

    assert len(requests) == 2
    assert requests[0].method == "PUT"
    assert requests[0].get_header("X-ms-blob-type") == "BlockBlob"
    assert requests[0].get_header("If-none-match") is None
    assert requests[0].get_header("Content-type") == "image/jpeg"


def test_upload_error_does_not_expose_sas(tmp_path: Path) -> None:
    def opener(request, timeout):
        raise HTTPError(request.full_url, 403, "forbidden", {}, None)

    with pytest.raises(BlobUploadError) as caught:
        upload_evidence_files(
            upload=targets(), manifest_path=bundle(tmp_path), opener=opener
        )
    assert caught.value.code == "ERR_UPLOAD_FAILED"
    assert "secret" not in str(caught.value)
