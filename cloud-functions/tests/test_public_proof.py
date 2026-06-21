from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import get_public_proof, issue_proof
from reality_cloud.storage import LocalJsonRepository


def _issue(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> str:
    session["status"] = "evidence_uploaded"
    repository.save_session(session)
    repository.save_manifest(manifest)
    _, response = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
    )
    return str(response["proof_id"])


def test_public_projection_contains_only_approved_fields(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issue(config, repository, session, manifest)

    status, payload = get_public_proof(
        proof_id,
        config=config,
        repository=repository,
    )

    assert status == 200
    assert set(payload) == {
        "proof_id",
        "schema_version",
        "device_id",
        "captured_at",
        "created_at",
        "challenge",
        "manifest_hash",
        "record_hash",
        "signature_algorithm",
        "key_id",
        "signed_at",
        "signature",
        "verification_url",
        "public_key",
        "sensors",
        "image_sha256",
        "audio_sha256",
    }
    assert set(payload["challenge"]) == {
        "type",
        "button_count_required",
        "button_count_actual",
        "result",
        "voice_verification",
    }
    serialized = json.dumps(payload)
    for private_value in (
        "session_id",
        "evidence_id",
        "nonce",
        "voice_code",
        "blob_path",
    ):
        assert private_value not in serialized
    assert payload["verification_url"] == (
        f"http://localhost:7071/verify/{proof_id}"
    )
    assert payload["sensors"] == manifest["sensors"]
    assert payload["image_sha256"] == manifest["files"]["image"]["sha256"]
    assert payload["audio_sha256"] == manifest["files"]["audio"]["sha256"]


def test_public_projection_rejects_invalid_stored_proof(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    repository.save_proof({"proof_id": "RP-broken"})

    with pytest.raises(ApiError) as captured:
        get_public_proof(
            "RP-broken",
            config=config,
            repository=repository,
        )
    assert captured.value.code == "ERR_PROOF_INVALID"
    assert captured.value.status_code == 422


def test_public_proof_http_returns_projection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    config: CloudConfig,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUB_SIGNING_SECRET", "test-signing-secret")
    repository = LocalJsonRepository(tmp_path)
    runtime_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=tmp_path,
        stub_signing_secret="test-signing-secret",
    )
    proof_id = _issue(runtime_config, repository, session, manifest)
    request = func.HttpRequest(
        method="GET",
        url=f"http://localhost/api/proofs/{proof_id}",
        headers={},
        params={},
        route_params={"proof_id": proof_id},
        body=b"",
    )

    response = function_app.get_public_proof_http(request)

    assert response.status_code == 200
    payload = json.loads(response.get_body())
    assert payload["proof_id"] == proof_id
    assert "session_id" not in payload
