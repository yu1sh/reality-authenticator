"""Proof Record construction and hash boundaries."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Mapping
from uuid import UUID

from reality_core import canonical_json_bytes, sha256_bytes

from .challenge import isoformat_milliseconds
from .signing import LocalStubSigner
from .signing_contract import Signer, SigningProfile

LEGACY_UNSIGNED_PROOF_FIELDS = (
    "schema_version",
    "proof_id",
    "evidence_id",
    "session_id",
    "device_id",
    "captured_at",
    "challenge",
    "manifest_hash",
    "created_at",
)
UNSIGNED_PROOF_FIELDS_V1_1 = LEGACY_UNSIGNED_PROOF_FIELDS + (
    "signature_algorithm",
    "key_id",
    "signed_at",
)
UNSIGNED_PROOF_FIELDS_V1_2 = UNSIGNED_PROOF_FIELDS_V1_1 + ("public_key",)


def public_key_metadata(profile: SigningProfile) -> dict[str, object]:
    if profile.algorithm == "STUB-HS256":
        return {"kty": "oct", "development_stub": True}
    if profile.algorithm != "PS256":
        raise ValueError("unsupported Proof signature algorithm")
    metadata = profile.public_key
    if not isinstance(metadata, Mapping):
        raise ValueError("PS256 public key metadata is required")
    modulus = metadata.get("n")
    exponent = metadata.get("e")
    bits = metadata.get("bits")
    if (
        metadata.get("kty") != "RSA"
        or not isinstance(modulus, str)
        or not modulus
        or not isinstance(exponent, str)
        or not exponent
        or isinstance(bits, bool)
        or not isinstance(bits, int)
        or bits < 3072
    ):
        raise ValueError("PS256 public key metadata is invalid")
    return {
        "kty": "RSA",
        "n": modulus,
        "e": exponent,
        "bits": bits,
    }


def calculate_manifest_hash(manifest: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(manifest)))


def unsigned_proof_payload(proof: Mapping[str, object]) -> dict[str, object]:
    """Select the exact fields covered by record_hash."""

    schema_version = proof.get("schema_version")
    if schema_version == "1.0":
        fields = LEGACY_UNSIGNED_PROOF_FIELDS
    elif schema_version == "1.1":
        fields = UNSIGNED_PROOF_FIELDS_V1_1
    elif schema_version == "1.2":
        fields = UNSIGNED_PROOF_FIELDS_V1_2
    else:
        raise ValueError("unsupported Proof schema version")
    return {field: proof[field] for field in fields}


def calculate_record_hash(proof: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(unsigned_proof_payload(proof)))


def build_proof_record(
    *,
    session: Mapping[str, object],
    manifest: Mapping[str, object],
    proof_uuid: UUID,
    created_at: datetime,
    public_web_base_url: str,
    signer: Signer | None = None,
    signing_profile: SigningProfile | None = None,
    signed_at: datetime | None = None,
    signing_secret: str | None = None,
    signature_key_id: str = "local-stub-v1",
) -> dict[str, object]:
    """Build and sign a schema 1.2 Proof Record."""

    if signer is None:
        if not signing_secret:
            raise ValueError("signer or signing_secret is required")
        signer = LocalStubSigner(signing_secret, signature_key_id)
    profile = signing_profile or signer.resolve_profile()
    public_key = public_key_metadata(profile)
    signed_at = signed_at or created_at
    manifest_hash = calculate_manifest_hash(manifest)
    proof_id = f"RP-{proof_uuid}"
    proof: dict[str, object] = {
        "schema_version": "1.2",
        "proof_id": proof_id,
        "evidence_id": f"EV-{manifest_hash[:32]}",
        "session_id": str(session["session_id"]),
        "device_id": str(session["device_id"]),
        "captured_at": str(manifest["edge_finished_at"]),
        "challenge": {
            "type": "button_and_voice",
            "nonce": str(session["challenge_nonce"]),
            "instruction_ja": str(session["challenge_text"]),
            "button_count_required": int(session["button_count"]),
            "button_count_actual": len(manifest["button_events"]),
            "voice_code": str(session["voice_code"]),
            "result": "verified",
            "voice_verification": "not_performed",
        },
        "manifest_hash": manifest_hash,
        "created_at": isoformat_milliseconds(created_at),
        "signature_algorithm": profile.algorithm,
        "key_id": profile.key_id,
        "signed_at": isoformat_milliseconds(signed_at),
        "public_key": public_key,
    }
    record_hash = calculate_record_hash(proof)
    signature = signer.sign_digest(bytes.fromhex(record_hash), profile.key_id)
    proof.update(
        {
            "record_hash": record_hash,
            "signature": base64.urlsafe_b64encode(signature)
            .rstrip(b"=")
            .decode("ascii"),
            "verification_url": (
                f"{public_web_base_url.rstrip('/')}/verify/{proof_id}"
            ),
        }
    )
    return proof
