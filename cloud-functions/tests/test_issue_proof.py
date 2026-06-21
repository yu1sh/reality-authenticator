from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import issue_proof
from reality_cloud.signing_contract import SigningProfile
from reality_cloud.signing_contract import SigningUnavailable
from reality_cloud.storage import LocalJsonRepository

RSA_PUBLIC_KEY = {
    "kty": "RSA",
    "n": "test-modulus",
    "e": "AQAB",
    "bits": 3072,
}


def test_issue_proof_saves_record_and_updates_session(
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    repository.save_session(accepted_session)
    repository.save_manifest(manifest)

    status, response = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
    )

    assert status == 201
    assert response["existing"] is False
    proof = repository.load_proof(str(response["proof_id"]))
    assert proof is not None
    assert proof["signature_algorithm"] == "STUB-HS256"
    assert response["verification_url"] == (
        f"http://localhost:7071/verify/{response['proof_id']}"
    )
    saved_session = repository.load_session("session-1")
    assert saved_session["status"] == "proof_issued"
    assert saved_session["proof_id"] == response["proof_id"]


def test_issue_proof_uses_ps256_signer_and_versioned_key(
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    class Signer:
        def __init__(self) -> None:
            self.digests = []

        def resolve_profile(self):
            return SigningProfile(
                "PS256",
                "https://vault.vault.azure.net/keys/reality-proof-signing/v1",
                RSA_PUBLIC_KEY,
            )

        def sign_digest(self, digest: bytes, key_id: str) -> bytes:
            self.digests.append((digest, key_id))
            return b"ps256-signature"

    signer = Signer()
    repository.save_session(accepted_session)
    repository.save_manifest(manifest)

    status, response = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
        signer=signer,
    )

    proof = repository.load_proof(str(response["proof_id"]))
    assert status == 201
    assert proof["schema_version"] == "1.2"
    assert proof["public_key"] == RSA_PUBLIC_KEY
    assert proof["signature_algorithm"] == "PS256"
    assert proof["key_id"].endswith("/v1")
    assert proof["signed_at"] == "2026-06-09T01:00:04.000+00:00"
    assert len(signer.digests[0][0]) == 32


def test_key_vault_failure_is_fail_closed(
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    class FailingSigner:
        def resolve_profile(self):
            raise SigningUnavailable("token=secret")

        def sign_digest(self, digest: bytes, key_id: str) -> bytes:
            raise AssertionError("must not sign")

    repository.save_session(accepted_session)
    repository.save_manifest(manifest)

    with pytest.raises(ApiError) as caught:
        issue_proof(
            {"session_id": "session-1"},
            config=config,
            repository=repository,
            signer=FailingSigner(),
        )

    assert caught.value.code == "ERR_SIGNATURE_FAILED"
    assert caught.value.status_code == 503
    assert "secret" not in caught.value.message
    audit_events = [
        json.loads(path.read_text())
        for path in (repository.root / "audit").rglob("*.json")
    ]
    assert any(
        event["event_type"] == "error"
        and event["detail"]["failure_code"] == "ERR_SIGNATURE_FAILED"
        for event in audit_events
    )


def test_ps256_without_public_key_metadata_is_rejected(
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    class InvalidSigner:
        def resolve_profile(self):
            return SigningProfile(
                "PS256",
                "https://vault.vault.azure.net/keys/reality-proof-signing/v1",
            )

        def sign_digest(self, digest: bytes, key_id: str) -> bytes:
            raise AssertionError("must not sign")

    repository.save_session(accepted_session)
    repository.save_manifest(manifest)

    with pytest.raises(ApiError) as caught:
        issue_proof(
            {"session_id": "session-1"},
            config=config,
            repository=repository,
            signer=InvalidSigner(),
        )

    assert caught.value.code == "ERR_SIGNATURE_FAILED"


def test_reissue_returns_existing_proof(
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    repository.save_session(accepted_session)
    repository.save_manifest(manifest)
    _, first = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
    )

    status, second = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        uuid_factory=lambda: UUID("22222222-2222-4222-8222-222222222222"),
    )

    assert status == 200
    assert second["existing"] is True
    assert second["proof_id"] == first["proof_id"]
    assert second["verification_url"] == (
        f"http://localhost:7071/verify/{first['proof_id']}"
    )


@pytest.mark.parametrize("_round", range(10))
def test_concurrent_issue_requests_converge_on_one_proof(
    _round: int,
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    repository.save_session(accepted_session)
    repository.save_manifest(manifest)
    proof_uuids = [
        UUID("11111111-1111-4111-8111-111111111111"),
        UUID("22222222-2222-4222-8222-222222222222"),
    ]

    def issue(index: int) -> tuple[int, dict[str, object]]:
        return issue_proof(
            {"session_id": "session-1"},
            config=config,
            repository=repository,
            uuid_factory=lambda: proof_uuids[index],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(issue, range(2)))

    assert sorted(status for status, _ in results) == [200, 201]
    assert len({response["proof_id"] for _, response in results}) == 1
    assert len(list((repository.root / "proofs").glob("*.json"))) == 1


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ("missing_session", "ERR_SESSION_NOT_FOUND"),
        ("wrong_status", "ERR_EVIDENCE_NOT_ACCEPTED"),
        ("missing_manifest", "ERR_MANIFEST_NOT_FOUND"),
        ("missing_secret", "ERR_SIGNATURE_FAILED"),
    ],
)
def test_issue_proof_rejects_invalid_state(
    setup: str,
    code: str,
    config: CloudConfig,
    repository: LocalJsonRepository,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    if setup != "missing_session":
        if setup == "wrong_status":
            accepted_session["status"] = "challenge_issued"
        repository.save_session(accepted_session)
    if setup not in {"missing_session", "missing_manifest"}:
        repository.save_manifest(manifest)
    if setup == "missing_secret":
        config = CloudConfig(
            allowed_device_ids=config.allowed_device_ids,
            local_data_dir=config.local_data_dir,
        )

    with pytest.raises(ApiError) as captured:
        issue_proof(
            {"session_id": "session-1"},
            config=config,
            repository=repository,
        )
    assert captured.value.code == code


def test_azure_http_issue_can_be_called_directly(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEVICE_API_KEY", "test-device-api-key")
    monkeypatch.setenv("STUB_SIGNING_SECRET", "test-signing-secret")
    repository = LocalJsonRepository(tmp_path)
    repository.save_session(accepted_session)
    repository.save_manifest(manifest)
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/api/proofs/issue",
        headers={
            "content-type": "application/json",
            "X-Device-Api-Key": "test-device-api-key",
        },
        params={},
        route_params={},
        body=json.dumps({"session_id": "session-1"}).encode(),
    )

    response = function_app.issue_proof_http(request)

    assert response.status_code == 201
    assert json.loads(response.get_body())["issued"] is True
