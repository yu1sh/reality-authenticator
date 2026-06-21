"""Local Proof Record verification."""

from __future__ import annotations

import base64
import hmac
from typing import Mapping

from .proof import calculate_manifest_hash, calculate_record_hash
from .signing import SIGNATURE_ALGORITHM, LocalStubVerifier
from .signing_contract import SigningUnavailable, Verifier
from .storage_contract import EvidenceVerification


def verify_proof_record(
    *,
    requested_proof_id: str,
    proof: Mapping[str, object],
    session: Mapping[str, object] | None,
    manifest: Mapping[str, object] | None,
    signing_secret: str | None,
    signature_key_id: str,
    verifier: Verifier | None = None,
    evidence_verification: EvidenceVerification | None = None,
    device: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return verification checks without raising for stored-data tampering."""

    manifest_hash = False
    calculated_manifest_hash = ""
    if manifest is not None and isinstance(proof.get("manifest_hash"), str):
        try:
            calculated_manifest_hash = calculate_manifest_hash(manifest)
            manifest_hash = hmac.compare_digest(
                calculated_manifest_hash,
                str(proof["manifest_hash"]),
            )
        except (TypeError, ValueError):
            manifest_hash = False

    challenge = proof.get("challenge")
    button_events = manifest.get("button_events") if manifest is not None else None
    button_count_actual = len(button_events) if isinstance(button_events, list) else -1
    proof_identity = (
        proof.get("proof_id") == requested_proof_id
        and session is not None
        and manifest is not None
        and proof.get("session_id") == session.get("session_id")
        and proof.get("device_id") == session.get("device_id")
        and session.get("proof_id") == requested_proof_id
        and session.get("status") == "proof_issued"
        and proof.get("captured_at") == manifest.get("edge_finished_at")
        and proof.get("evidence_id") == f"EV-{calculated_manifest_hash[:32]}"
        and isinstance(challenge, dict)
        and challenge.get("type") == "button_and_voice"
        and challenge.get("nonce") == session.get("challenge_nonce")
        and challenge.get("instruction_ja") == session.get("challenge_text")
        and challenge.get("button_count_required") == session.get("button_count")
        and challenge.get("button_count_actual") == button_count_actual
        and challenge.get("voice_code") == session.get("voice_code")
        and challenge.get("result") == "verified"
        and challenge.get("voice_verification") == "not_performed"
    )

    record_hash = False
    calculated_record_hash = ""
    try:
        calculated_record_hash = calculate_record_hash(proof)
        stored_record_hash = proof.get("record_hash")
        record_hash = isinstance(stored_record_hash, str) and hmac.compare_digest(
            calculated_record_hash,
            stored_record_hash,
        )
    except (KeyError, TypeError, ValueError):
        record_hash = False

    algorithm = proof.get("signature_algorithm")
    key_id = (
        proof.get("signature_key_id")
        if proof.get("schema_version") == "1.0"
        else proof.get("key_id")
    )
    signature: bool | None = (
        None if algorithm == "PS256" and verifier is None else False
    )
    if (
        record_hash
        and isinstance(algorithm, str)
        and isinstance(key_id, str)
        and isinstance(proof.get("signature"), str)
    ):
        try:
            encoded = str(proof["signature"])
            padding = "=" * (-len(encoded) % 4)
            signature_bytes = base64.b64decode(
                encoded + padding, altchars=b"-_", validate=True
            )
            digest = bytes.fromhex(calculated_record_hash)
            if algorithm == SIGNATURE_ALGORITHM:
                if signing_secret:
                    signature = LocalStubVerifier(
                        signing_secret, signature_key_id
                    ).verify_digest(digest, signature_bytes, algorithm, key_id)
            elif verifier is not None:
                signature = verifier.verify_digest(
                    digest, signature_bytes, algorithm, key_id
                )
        except (ValueError, TypeError):
            signature = False
        except SigningUnavailable:
            signature = None
    image_hash = (
        evidence_verification.image_hash
        if evidence_verification is not None
        else None
    )
    audio_hash = (
        evidence_verification.audio_hash
        if evidence_verification is not None
        else None
    )
    device_status = (
        device.get("status") == "active"
        if device is not None
        else None
    )
    checks = {
        "proof_identity": proof_identity,
        "manifest_hash": manifest_hash,
        "record_hash": record_hash,
        "signature": signature,
        "image_hash": image_hash,
        "audio_hash": audio_hash,
        "device_status": device_status,
    }
    warnings: list[str] = []
    if algorithm == SIGNATURE_ALGORITHM:
        warnings.append("STUB_SIGNATURE_NOT_KEY_VAULT")
    if (
        evidence_verification is None
        or evidence_verification.verified is not True
    ):
        warnings.append("EVIDENCE_BYTES_NOT_VERIFIED")
    if signature is None:
        warnings.append("SIGNATURE_VERIFICATION_UNAVAILABLE")
    if device_status is None:
        warnings.append("DEVICE_STATUS_NOT_VERIFIED")
    required_checks = (
        proof_identity,
        manifest_hash,
        record_hash,
        signature,
    )
    invalid = any(value is False for value in checks.values())
    cryptographically_valid = all(value is True for value in required_checks)
    status = (
        "INVALID"
        if invalid
        else "WARNING"
        if (
            warnings
            or any(value is None for value in checks.values())
            or not cryptographically_valid
        )
        else "VALID"
    )
    return {
        "proof_id": requested_proof_id,
        "valid": status == "VALID",
        "status": status,
        "checks": checks,
        "signature_algorithm": proof.get("signature_algorithm"),
        "warnings": warnings,
    }
