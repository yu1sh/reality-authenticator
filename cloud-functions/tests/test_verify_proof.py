from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import issue_proof, verify_proof
from reality_cloud.proof import calculate_manifest_hash, calculate_record_hash
from reality_cloud.signing import sign_record_hash
from reality_cloud.signing_contract import SigningProfile
from reality_cloud.signing_contract import SigningUnavailable
from reality_cloud.storage import LocalJsonRepository
from reality_cloud.storage_contract import EvidenceVerification

RSA_PUBLIC_KEY = {
    "kty": "RSA",
    "n": "test-modulus",
    "e": "AQAB",
    "bits": 3072,
}


def _issued_proof(
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


def test_valid_proof_passes_all_checks(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issued_proof(config, repository, session, manifest)

    status, response = verify_proof(
        proof_id,
        config=config,
        repository=repository,
    )

    assert status == 200
    assert response["valid"] is False
    assert response["status"] == "WARNING"
    assert all(
        response["checks"][name]
        for name in ("proof_identity", "manifest_hash", "record_hash", "signature")
    )
    assert response["warnings"] == [
        "STUB_SIGNATURE_NOT_KEY_VAULT",
        "EVIDENCE_BYTES_NOT_VERIFIED",
        "DEVICE_STATUS_NOT_VERIFIED",
    ]


def test_verified_azure_bytes_remove_unverified_warning(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issued_proof(config, repository, session, manifest)
    saved = repository.load_session("session-1")
    assert saved is not None
    saved["evidence_bytes_verified"] = True
    repository.save_session(saved)

    _, response = verify_proof(proof_id, config=config, repository=repository)

    assert response["valid"] is False
    assert response["status"] == "WARNING"
    assert response["warnings"] == [
        "STUB_SIGNATURE_NOT_KEY_VAULT",
        "EVIDENCE_BYTES_NOT_VERIFIED",
        "DEVICE_STATUS_NOT_VERIFIED",
    ]


def test_ps256_with_verified_media_and_active_device_is_valid(
    config: CloudConfig,
    tmp_path,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    class VerifiedRepository(LocalJsonRepository):
        def verify_evidence_files(self, value):
            return EvidenceVerification(
                verified=True,
                image_hash=True,
                audio_hash=True,
            )

    key_id = "https://vault.vault.azure.net/keys/reality-proof-signing/v1"

    class Signer:
        def resolve_profile(self):
            return SigningProfile(
                "PS256",
                key_id,
                {"kty": "RSA", "n": "abc", "e": "AQAB", "bits": 3072},
            )

        def sign_digest(self, digest: bytes, requested_key_id: str) -> bytes:
            return b"signature"

    class Verifier:
        def verify_digest(self, *args):
            return True

    repository = VerifiedRepository(tmp_path)
    session["status"] = "evidence_uploaded"
    repository.save_session(session)
    repository.save_manifest(manifest)
    repository.save_device(
        {
            "device_id": "raspi-anchor-01",
            "status": "active",
            "display_name": "Anchor",
        }
    )
    _, issued = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        signer=Signer(),
    )

    _, response = verify_proof(
        str(issued["proof_id"]),
        config=config,
        repository=repository,
        verifier=Verifier(),
    )

    assert response["valid"] is True
    assert response["status"] == "VALID"
    assert response["warnings"] == []
    assert all(response["checks"].values())


def test_disabled_device_makes_verification_invalid(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issued_proof(config, repository, session, manifest)
    repository.save_device(
        {
            "device_id": "raspi-anchor-01",
            "display_name": "Anchor",
            "status": "disabled",
        }
    )

    _, response = verify_proof(
        proof_id,
        config=config,
        repository=repository,
    )

    assert response["status"] == "INVALID"
    assert response["valid"] is False
    assert response["checks"]["device_status"] is False


def test_legacy_schema_1_0_stub_proof_remains_verifiable(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = "RP-legacy"
    session["status"] = "proof_issued"
    session["proof_id"] = proof_id
    repository.save_session(session)
    repository.save_manifest(manifest)
    manifest_hash = calculate_manifest_hash(manifest)
    proof = {
        "schema_version": "1.0",
        "proof_id": proof_id,
        "evidence_id": f"EV-{manifest_hash[:32]}",
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "captured_at": manifest["edge_finished_at"],
        "challenge": {
            "type": "button_and_voice",
            "nonce": session["challenge_nonce"],
            "instruction_ja": session["challenge_text"],
            "button_count_required": session["button_count"],
            "button_count_actual": 2,
            "voice_code": session["voice_code"],
            "result": "verified",
            "voice_verification": "not_performed",
        },
        "manifest_hash": manifest_hash,
        "created_at": "2026-06-09T01:00:04.000+00:00",
    }
    proof["record_hash"] = calculate_record_hash(proof)
    proof["signature"] = sign_record_hash(
        str(proof["record_hash"]), "test-signing-secret"
    )
    proof["signature_algorithm"] = "STUB-HS256"
    proof["signature_key_id"] = "local-stub-v1"
    proof["verification_url"] = f"http://localhost:7071/verify/{proof_id}"
    repository.save_proof(proof)

    _, response = verify_proof(proof_id, config=config, repository=repository)

    assert response["valid"] is False
    assert "STUB_SIGNATURE_NOT_KEY_VAULT" in response["warnings"]


def test_legacy_schema_1_1_stub_proof_remains_verifiable(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = "RP-legacy-1-1"
    session["status"] = "proof_issued"
    session["proof_id"] = proof_id
    repository.save_session(session)
    repository.save_manifest(manifest)
    manifest_hash = calculate_manifest_hash(manifest)
    proof = {
        "schema_version": "1.1",
        "proof_id": proof_id,
        "evidence_id": f"EV-{manifest_hash[:32]}",
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "captured_at": manifest["edge_finished_at"],
        "challenge": {
            "type": "button_and_voice",
            "nonce": session["challenge_nonce"],
            "instruction_ja": session["challenge_text"],
            "button_count_required": session["button_count"],
            "button_count_actual": 2,
            "voice_code": session["voice_code"],
            "result": "verified",
            "voice_verification": "not_performed",
        },
        "manifest_hash": manifest_hash,
        "created_at": "2026-06-09T01:00:04.000+00:00",
        "signature_algorithm": "STUB-HS256",
        "key_id": "local-stub-v1",
        "signed_at": "2026-06-09T01:00:04.000+00:00",
    }
    proof["record_hash"] = calculate_record_hash(proof)
    proof["signature"] = sign_record_hash(
        str(proof["record_hash"]), "test-signing-secret"
    )
    proof["verification_url"] = f"http://localhost:7071/verify/{proof_id}"
    repository.save_proof(proof)

    _, response = verify_proof(proof_id, config=config, repository=repository)

    assert response["status"] == "WARNING"
    assert response["checks"]["record_hash"] is True
    assert response["checks"]["signature"] is True


def test_ps256_proof_uses_injected_verifier_without_stub_warning(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    key_id = "https://vault.vault.azure.net/keys/reality-proof-signing/v1"

    class Signer:
        def resolve_profile(self):
            return SigningProfile("PS256", key_id, RSA_PUBLIC_KEY)

        def sign_digest(self, digest: bytes, requested_key_id: str) -> bytes:
            assert requested_key_id == key_id
            return b"ps256-signature"

    class Verifier:
        def verify_digest(
            self,
            digest: bytes,
            signature: bytes,
            algorithm: str,
            requested_key_id: str,
        ) -> bool:
            return (
                len(digest) == 32
                and signature == b"ps256-signature"
                and algorithm == "PS256"
                and requested_key_id == key_id
            )

    session["status"] = "evidence_uploaded"
    repository.save_session(session)
    repository.save_manifest(manifest)
    _, issued = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
        signer=Signer(),
    )

    _, response = verify_proof(
        str(issued["proof_id"]),
        config=config,
        repository=repository,
        verifier=Verifier(),
    )

    assert response["valid"] is False
    assert "STUB_SIGNATURE_NOT_KEY_VAULT" not in response["warnings"]


def test_key_vault_verification_unavailable_returns_warning(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    class Signer:
        def resolve_profile(self):
            return SigningProfile(
                "PS256",
                "https://vault.vault.azure.net/keys/reality-proof-signing/v1",
                RSA_PUBLIC_KEY,
            )

        def sign_digest(self, digest: bytes, key_id: str) -> bytes:
            return b"signature"

    class FailingVerifier:
        def verify_digest(self, *args):
            raise SigningUnavailable("token=secret")

    session["status"] = "evidence_uploaded"
    repository.save_session(session)
    repository.save_manifest(manifest)
    _, issued = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        signer=Signer(),
    )

    status, response = verify_proof(
        str(issued["proof_id"]),
        config=config,
        repository=repository,
        verifier=FailingVerifier(),
    )

    assert status == 200
    assert response["status"] == "WARNING"
    assert response["checks"]["signature"] is None
    assert "SIGNATURE_VERIFICATION_UNAVAILABLE" in response["warnings"]


@pytest.mark.parametrize(
    "target",
    [
        "proof",
        "manifest",
        "non_finite_manifest",
        "signature",
        "key_id",
        "public_key",
        "session_id",
        "challenge",
    ],
)
def test_tampering_is_reported_as_invalid(
    target: str,
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issued_proof(config, repository, session, manifest)
    proof = repository.load_proof(proof_id)
    if target == "proof":
        proof["device_id"] = "other-device"
        repository.save_proof(proof)
    elif target == "manifest":
        changed = deepcopy(manifest)
        changed["sensors"]["temperature_c"] = 99.0
        repository.save_manifest(changed)
    elif target == "non_finite_manifest":
        changed = deepcopy(manifest)
        changed["sensors"]["temperature_c"] = float("nan")
        manifest_path = (
            repository.root / "evidence" / "session-1" / "manifest.json"
        )
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    elif target == "signature":
        proof["signature"] = f"{proof['signature']}x"
        repository.save_proof(proof)
    elif target == "key_id":
        proof["key_id"] = "other-key"
        repository.save_proof(proof)
    elif target == "public_key":
        proof["public_key"]["bits"] = 4096
        repository.save_proof(proof)
    elif target == "session_id":
        proof["session_id"] = "../invalid"
        repository.save_proof(proof)
    else:
        proof["challenge"]["voice_code"] = "9999"
        repository.save_proof(proof)

    status, response = verify_proof(
        proof_id,
        config=config,
        repository=repository,
    )

    assert status == 200
    assert response["valid"] is False
    assert not all(response["checks"].values())


def test_missing_proof_returns_not_found(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    with pytest.raises(ApiError) as captured:
        verify_proof("RP-missing", config=config, repository=repository)
    assert captured.value.code == "ERR_PROOF_NOT_FOUND"
    assert captured.value.status_code == 404


def test_azure_http_verify_can_be_called_directly(
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
    proof_id = _issued_proof(runtime_config, repository, session, manifest)
    request = func.HttpRequest(
        method="POST",
        url=f"http://localhost/api/proofs/{proof_id}/verify",
        headers={},
        params={},
        route_params={"proof_id": proof_id},
        body=b"",
    )

    response = function_app.verify_proof_http(request)

    assert response.status_code == 200
    assert json.loads(response.get_body())["valid"] is False
