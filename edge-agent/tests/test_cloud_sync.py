from __future__ import annotations

import json
from pathlib import Path

import pytest

from reality_edge.cloud_client import CloudClientError
from reality_edge.blob_upload import BlobUploadError
from reality_edge.cloud_sync import CloudSyncError, run_cloud_sync


class FakeCloudClient:
    api_base_url = "http://localhost:7071/api"

    def __init__(self, *, ingest_error: bool = False, verify_valid: bool = True):
        self.calls = []
        self.ingest_error = ingest_error
        self.verify_valid = verify_valid
        self.verification_url = "http://localhost:7071/verify/RP-1"

    def start_session(self, device_id: str):
        self.calls.append(("start", device_id))
        return {
            "session_id": "cloud-session",
            "device_id": device_id,
            "challenge": {
                "instruction_ja": "challenge",
                "button_count": 3,
                "voice_code": "0007",
                "time_limit_seconds": 10,
            },
            "expires_at": "2100-01-01T00:00:00.000+00:00",
        }

    def ingest_evidence(self, manifest):
        self.calls.append(("ingest", manifest))
        if self.ingest_error:
            raise CloudClientError("ERR_SESSION_EXPIRED", "expired")
        return {"accepted": True}

    def issue_proof(self, session_id: str):
        self.calls.append(("issue", session_id))
        return {
            "issued": True,
            "proof_id": "RP-1",
            "verification_url": self.verification_url,
        }

    def verify_proof(self, proof_id: str):
        self.calls.append(("verify", proof_id))
        return {
            "proof_id": proof_id,
            "valid": self.verify_valid,
            "checks": {"signature": self.verify_valid},
        }


class UploadCloudClient(FakeCloudClient):
    def start_session(self, device_id: str):
        response = super().start_session(device_id)
        response["upload"] = {
            "mode": "sas_url",
            "expires_at": "2100-01-01T00:00:00.000+00:00",
            "image": {},
            "audio": {},
        }
        return response


def test_cloud_sync_uses_cloud_session_and_challenge(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    client = FakeCloudClient()

    result = run_cloud_sync(
        client=client,
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        device_id="device-1",
        verify_base_url="http://localhost:7071",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_id"] == "cloud-session"
    assert manifest["challenge"]["button_count"] == 3
    assert len(manifest["button_events"]) == 3
    assert [call[0] for call in client.calls] == [
        "start",
        "ingest",
        "issue",
        "verify",
    ]
    assert result.qr_url == "http://localhost:7071/api/proofs/RP-1/qr"


def test_cloud_sync_uses_injected_capture(tmp_path: Path, fixtures_dir: Path) -> None:
    client = FakeCloudClient()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "session_id": "cloud-session",
                "challenge": {"button_count": 3},
            }
        )
    )
    calls = []

    run_cloud_sync(
        client=client,
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        device_id="device-1",
        verify_base_url="http://localhost:7071",
        capture=lambda session_id, challenge, expires_at: (
            calls.append((session_id, challenge, expires_at)) or manifest_path
        ),
    )

    assert calls[0][0] == "cloud-session"
    assert calls[0][1]["button_count"] == 3


def test_cloud_sync_uploads_before_ingest(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    client = UploadCloudClient()
    calls = []

    run_cloud_sync(
        client=client,
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        device_id="device-1",
        verify_base_url="http://localhost:7071",
        uploader=lambda **kwargs: calls.append(kwargs),
    )

    assert len(calls) == 1
    assert calls[0]["upload"]["mode"] == "sas_url"
    assert [call[0] for call in client.calls] == [
        "start",
        "ingest",
        "issue",
        "verify",
    ]


def test_upload_failure_stops_before_ingest(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    client = UploadCloudClient()

    def fail_upload(**kwargs):
        raise BlobUploadError("ERR_UPLOAD_FAILED", "upload failed")

    with pytest.raises(CloudSyncError) as captured:
        run_cloud_sync(
            client=client,
            output_dir=tmp_path,
            fixtures_dir=fixtures_dir,
            device_id="device-1",
            verify_base_url="http://localhost:7071",
            uploader=fail_upload,
        )

    assert captured.value.code == "ERR_UPLOAD_FAILED"
    assert [call[0] for call in client.calls] == ["start"]


def test_ingest_failure_stops_before_proof_and_updates_log(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    client = FakeCloudClient(ingest_error=True)

    with pytest.raises(CloudClientError) as captured:
        run_cloud_sync(
            client=client,
            output_dir=tmp_path,
            fixtures_dir=fixtures_dir,
            device_id="device-1",
            verify_base_url="http://localhost:7071",
        )

    assert captured.value.code == "ERR_SESSION_EXPIRED"
    assert [call[0] for call in client.calls] == ["start", "ingest"]
    log = (tmp_path / "cloud-session" / "edge.log").read_text()
    assert "failure_code=ERR_SESSION_EXPIRED" in log


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://other-host:7071/verify/RP-1",
        "http://localhost:7071/verify/RP-other",
    ],
)
def test_verification_url_is_strictly_validated(
    tmp_path: Path,
    fixtures_dir: Path,
    url: str,
) -> None:
    client = FakeCloudClient()
    client.verification_url = url

    with pytest.raises(CloudSyncError) as captured:
        run_cloud_sync(
            client=client,
            output_dir=tmp_path,
            fixtures_dir=fixtures_dir,
            device_id="device-1",
            verify_base_url="http://localhost:7071",
        )

    assert captured.value.code == "ERR_VERIFICATION_URL"
