from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from reality_cloud.proof import (
    build_proof_record,
    calculate_manifest_hash,
    calculate_record_hash,
)


def test_proof_generation_is_deterministic(
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof = build_proof_record(
        session=accepted_session,
        manifest=manifest,
        proof_uuid=UUID("11111111-1111-4111-8111-111111111111"),
        created_at=datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        signing_secret="test-signing-secret",
        signature_key_id="local-stub-v1",
        public_web_base_url="http://localhost:7071",
    )

    assert proof["proof_id"] == "RP-11111111-1111-4111-8111-111111111111"
    assert proof["schema_version"] == "1.2"
    assert proof["evidence_id"] == f"EV-{proof['manifest_hash'][:32]}"
    assert proof["captured_at"] == manifest["edge_finished_at"]
    assert proof["challenge"]["button_count_actual"] == 2
    assert proof["challenge"]["voice_verification"] == "not_performed"
    assert proof["signature_algorithm"] == "STUB-HS256"
    assert proof["key_id"] == "local-stub-v1"
    assert "signature_key_id" not in proof
    assert proof["signed_at"] == "2026-06-09T01:00:04.000+00:00"
    assert proof["created_at"] == "2026-06-09T01:00:04.000+00:00"
    assert proof["public_key"] == {
        "kty": "oct",
        "development_stub": True,
    }


def test_manifest_hash_uses_canonical_json(manifest: dict[str, object]) -> None:
    reversed_manifest = dict(reversed(list(manifest.items())))

    assert calculate_manifest_hash(manifest) == calculate_manifest_hash(
        reversed_manifest
    )


def test_signed_field_changes_record_hash(
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof = build_proof_record(
        session=accepted_session,
        manifest=manifest,
        proof_uuid=UUID("11111111-1111-4111-8111-111111111111"),
        created_at=datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        signing_secret="test-signing-secret",
        signature_key_id="local-stub-v1",
        public_web_base_url="http://localhost:7071",
    )
    changed = deepcopy(proof)
    changed["device_id"] = "other-device"

    assert calculate_record_hash(changed) != proof["record_hash"]


def test_signature_metadata_is_split_by_hash_boundary(
    accepted_session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof = build_proof_record(
        session=accepted_session,
        manifest=manifest,
        proof_uuid=UUID("11111111-1111-4111-8111-111111111111"),
        created_at=datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        signing_secret="test-signing-secret",
        signature_key_id="local-stub-v1",
        public_web_base_url="http://localhost:7071",
    )
    changed = deepcopy(proof)
    changed["signature"] = "changed"
    changed["verification_url"] = "https://example.invalid"

    assert calculate_record_hash(changed) == proof["record_hash"]

    for field in ("signature_algorithm", "key_id", "signed_at", "public_key"):
        changed = deepcopy(proof)
        changed[field] = "changed"
        assert calculate_record_hash(changed) != proof["record_hash"]
