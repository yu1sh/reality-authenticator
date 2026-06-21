"""Application handlers independent of Azure HTTP objects."""

from __future__ import annotations

from datetime import datetime, timedelta
import time
from uuid import UUID, uuid4

from reality_core import canonical_json_bytes, sha256_bytes

from .blob_verification import BlobVerificationError
from .audit import write_audit_log
from .challenge import (
    Clock,
    RandBelow,
    UuidFactory,
    create_session,
    isoformat_milliseconds,
    utc_now,
)
from .config import CloudConfig
from .devices import require_active_device
from .errors import ApiError
from .manifest import validate_manifest
from .iot import CommandDispatcher, IotUnavailable, create_command_dispatcher
from .presentation import (
    public_proof_projection,
    render_verification_page,
    verification_state,
)
from .proof import build_proof_record, public_key_metadata
from .qr import generate_qr_png, verification_page_url
from .signing import create_signer, create_verifier
from .signing_contract import (
    Signer,
    SigningProfile,
    SigningUnavailable,
    Verifier,
)
from .storage_contract import (
    EvidenceVerification,
    StorageConflict,
    StorageRepository,
    StorageUnavailable,
)
from .verification import verify_proof_record


def _storage_error() -> ApiError:
    return ApiError("ERR_STORAGE_UNAVAILABLE", "storage is unavailable", 503)


def start_session(
    payload: object,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
    uuid_factory: UuidFactory,
    randbelow: RandBelow,
    dispatcher: CommandDispatcher | None = None,
) -> tuple[int, dict[str, object]]:
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object", 400)
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", "device_id is required", 400)
    device_id = device_id.strip()
    try:
        require_active_device(
            device_id,
            config=config,
            repository=repository,
            clock=clock,
        )
    except StorageUnavailable as error:
        raise _storage_error() from error

    session, response = create_session(
        device_id=device_id,
        config=config,
        clock=clock,
        uuid_factory=uuid_factory,
        randbelow=randbelow,
    )
    created = None
    try:
        created = repository.create_session(session)
        upload = (
            repository.create_upload_targets(
                str(session["session_id"]),
                isoformat_milliseconds(
                    clock()
                    + timedelta(seconds=config.azure_storage_sas_ttl_seconds)
                ),
            )
            if config.use_iot_hub
            else None
        )
    except StorageConflict as error:
        raise ApiError("ERR_STORAGE_CONFLICT", "Session already exists", 409) from error
    except StorageUnavailable as error:
        if created is not None:
            storage_error = _storage_error()
            try:
                _mark_failed(
                    repository,
                    session,
                    storage_error,
                    clock=clock,
                )
            except (StorageConflict, StorageUnavailable):
                pass
        raise _storage_error() from error
    session["status"] = "challenge_issued"
    try:
        challenged = repository.replace_session(session, created.etag)
    except StorageConflict as error:
        raise ApiError(
            "ERR_STORAGE_CONFLICT",
            "Session changed before challenge issue",
            409,
        ) from error
    write_audit_log(
        repository,
        "session_created",
        clock=clock,
        session_id=str(session["session_id"]),
        device_id=device_id,
        message="Session created",
    )
    write_audit_log(
        repository,
        "session_status_updated",
        clock=clock,
        session_id=str(session["session_id"]),
        device_id=device_id,
        message="Session status: challenge_issued",
        detail={"status": "challenge_issued"},
    )
    if config.use_iot_hub:
        command = {
            "message_type": "start_session",
            "command_id": str(session["session_id"]),
            **response,
        }
        if upload is not None:
            command["upload"] = upload
        try:
            if upload is None:
                raise IotUnavailable(
                    "IoT Hub command requires Blob upload targets"
                )
            active_dispatcher = dispatcher or create_command_dispatcher(config)
            if active_dispatcher is None:
                raise IotUnavailable("IoT Hub dispatcher is unavailable")
            session["status"] = "waiting_device"
            repository.replace_session(session, challenged.etag)
            write_audit_log(
                repository,
                "session_status_updated",
                clock=clock,
                session_id=str(session["session_id"]),
                device_id=device_id,
                message="Session status: waiting_device",
                detail={"status": "waiting_device"},
            )
            active_dispatcher.send_start_session(device_id, command)
            write_audit_log(
                repository,
                "device_command_dispatched",
                clock=clock,
                session_id=str(session["session_id"]),
                device_id=device_id,
                message="StartSession command dispatched",
            )
        except (IotUnavailable, StorageConflict, StorageUnavailable) as error:
            _mark_failed(
                repository,
                session,
                ApiError(
                    "ERR_DEVICE_COMMAND",
                    "device command could not be dispatched",
                    503,
                ),
                clock=clock,
            )
            raise ApiError(
                "ERR_DEVICE_COMMAND",
                "device command could not be dispatched",
                503,
            ) from error
    else:
        session["status"] = "waiting_device"
        try:
            repository.replace_session(session, challenged.etag)
        except StorageConflict as error:
            raise ApiError(
                "ERR_STORAGE_CONFLICT",
                "Session changed before device wait",
                409,
            ) from error
        write_audit_log(
            repository,
            "session_status_updated",
            clock=clock,
            session_id=str(session["session_id"]),
            device_id=device_id,
            message="Session status: waiting_device",
            detail={"status": "waiting_device"},
        )
    return 201, response


def _mark_failed(
    repository: StorageRepository,
    session: dict[str, object],
    error: ApiError,
    *,
    clock: Clock = utc_now,
) -> None:
    session["status"] = "failed"
    session["failure_code"] = error.code
    repository.save_session(session)
    write_audit_log(
        repository,
        "session_status_updated",
        clock=clock,
        session_id=str(session.get("session_id") or ""),
        device_id=(
            str(session.get("device_id"))
            if isinstance(session.get("device_id"), str)
            else None
        ),
        message="Session status: failed",
        detail={"status": "failed", "failure_code": error.code},
    )
    write_audit_log(
        repository,
        "error",
        clock=clock,
        session_id=str(session.get("session_id") or ""),
        device_id=(
            str(session.get("device_id"))
            if isinstance(session.get("device_id"), str)
            else None
        ),
        message=error.message,
        detail={"failure_code": error.code},
    )


def ingest_evidence(
    payload: object,
    *,
    repository: StorageRepository,
    clock: Clock = utc_now,
) -> tuple[int, dict[str, object]]:
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object", 400)

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ApiError("ERR_INVALID_REQUEST", "session_id is required", 400)

    try:
        record = repository.load_session_record(session_id)
    except ValueError as error:
        raise ApiError("ERR_INVALID_REQUEST", str(error), 400) from error
    if record is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Session was not found", 404)
    session = record.value

    existing_manifest = repository.load_manifest(session_id)
    if existing_manifest is not None:
        if canonical_json_bytes(existing_manifest) == canonical_json_bytes(payload):
            return 200, {
                "accepted": True,
                "session_id": session_id,
                "status": "evidence_uploaded",
            }
        raise ApiError(
            "ERR_EVIDENCE_CONFLICT",
            "different evidence already exists for this Session",
            409,
        )
    if session.get("status") not in {
        "challenge_issued",
        "waiting_device",
        "capturing",
    }:
        raise ApiError(
            "ERR_EVIDENCE_NOT_ACCEPTED",
            "Session cannot accept evidence in its current state",
            409,
        )

    try:
        validate_manifest(payload, session, now=clock())
        verification = repository.verify_evidence_files(payload)
    except BlobVerificationError as error:
        api_error = ApiError(error.code, error.message, 422)
        _mark_failed(repository, session, api_error, clock=clock)
        repository.save_ingest_result(
            {
                "session_id": session_id,
                "status": "failed",
                "failure_code": error.code,
            }
        )
        raise api_error from error
    except StorageUnavailable as error:
        raise _storage_error() from error
    except ApiError as error:
        _mark_failed(repository, session, error, clock=clock)
        repository.save_ingest_result(
            {
                "session_id": session_id,
                "status": "failed",
                "failure_code": error.code,
            }
        )
        raise

    try:
        repository.save_manifest(payload)
    except StorageConflict as error:
        stored = repository.load_manifest(session_id)
        if stored is None or canonical_json_bytes(stored) != canonical_json_bytes(
            payload
        ):
            raise ApiError(
                "ERR_EVIDENCE_CONFLICT",
                "different evidence already exists for this Session",
                409,
            ) from error
    except StorageUnavailable as error:
        raise _storage_error() from error
    if session.get("status") == "challenge_issued":
        session["status"] = "waiting_device"
        try:
            record = repository.replace_session(session, record.etag)
        except StorageConflict as error:
            raise ApiError(
                "ERR_STORAGE_CONFLICT",
                "Session changed during ingest",
                409,
            ) from error
        write_audit_log(
            repository,
            "session_status_updated",
            clock=clock,
            session_id=session_id,
            device_id=str(session["device_id"]),
            message="Session status: waiting_device",
            detail={"status": "waiting_device"},
        )
    if session.get("status") == "waiting_device":
        session["status"] = "capturing"
        try:
            record = repository.replace_session(session, record.etag)
        except StorageConflict as error:
            raise ApiError(
                "ERR_STORAGE_CONFLICT",
                "Session changed during ingest",
                409,
            ) from error
        write_audit_log(
            repository,
            "session_status_updated",
            clock=clock,
            session_id=session_id,
            device_id=str(session["device_id"]),
            message="Session status: capturing",
            detail={"status": "capturing"},
        )
    session["status"] = "evidence_uploaded"
    session["failure_code"] = None
    session["evidence_bytes_verified"] = verification.verified
    session["evidence_verified_at"] = verification.verified_at
    try:
        repository.replace_session(session, record.etag)
        files = payload.get("files")
        image = files.get("image", {}) if isinstance(files, dict) else {}
        audio = files.get("audio", {}) if isinstance(files, dict) else {}
        repository.save_ingest_result(
            {
                "session_id": session_id,
                "status": "evidence_uploaded",
                "failure_code": None,
                "manifest_hash": sha256_bytes(canonical_json_bytes(payload)),
                "evidence_bytes_verified": verification.verified,
                "verified_at": verification.verified_at,
                "image_blob_path": image.get("blob_path"),
                "image_size_bytes": image.get("size_bytes"),
                "image_sha256": image.get("sha256"),
                "audio_blob_path": audio.get("blob_path"),
                "audio_size_bytes": audio.get("size_bytes"),
                "audio_sha256": audio.get("sha256"),
            }
        )
    except StorageConflict as error:
        latest = repository.load_session_record(session_id)
        if latest is None or latest.value.get("status") != "evidence_uploaded":
            raise ApiError(
                "ERR_STORAGE_CONFLICT", "Session changed during ingest", 409
            ) from error
    except StorageUnavailable as error:
        raise _storage_error() from error
    write_audit_log(
        repository,
        "session_status_updated",
        clock=clock,
        session_id=session_id,
        device_id=str(session["device_id"]),
        message="Session status: evidence_uploaded",
        detail={"status": "evidence_uploaded"},
    )
    write_audit_log(
        repository,
        "evidence_ingested",
        clock=clock,
        session_id=session_id,
        device_id=str(session["device_id"]),
        message="Evidence Manifest accepted",
    )
    return 200, {
        "accepted": True,
        "session_id": session_id,
        "status": "evidence_uploaded",
    }


def _proof_response(
    proof: dict[str, object],
    *,
    existing: bool,
    public_web_base_url: str,
) -> dict[str, object]:
    proof_id = str(proof["proof_id"])
    return {
        "issued": True,
        "existing": existing,
        "proof_id": proof_id,
        "verification_url": verification_page_url(
            public_web_base_url,
            proof_id,
        ),
    }


def issue_proof(
    payload: object,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
    uuid_factory: UuidFactory = uuid4,
    signer: Signer | None = None,
) -> tuple[int, dict[str, object]]:
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object", 400)
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ApiError("ERR_INVALID_REQUEST", "session_id is required", 400)

    max_attempts = 8
    for _attempt in range(max_attempts):
        try:
            record = repository.load_session_record(session_id)
        except ValueError as error:
            raise ApiError("ERR_INVALID_REQUEST", str(error), 400) from error
        if record is None:
            raise ApiError("ERR_SESSION_NOT_FOUND", "Session was not found", 404)
        session = record.value

        existing_proof_id = session.get("proof_id")
        if existing_proof_id is not None:
            if not isinstance(existing_proof_id, str):
                raise ApiError(
                    "ERR_PROOF_CONFLICT",
                    "Session proof_id is invalid",
                    409,
                )
            try:
                existing_proof = repository.load_proof(existing_proof_id)
            except (TypeError, ValueError) as error:
                raise ApiError(
                    "ERR_PROOF_CONFLICT",
                    "Session proof_id is invalid",
                    409,
                ) from error
            if existing_proof is not None and (
                existing_proof.get("session_id") != session_id
                or session.get("status")
                not in {"verified", "proof_issuing", "proof_issued"}
            ):
                raise ApiError(
                    "ERR_PROOF_CONFLICT",
                    "Session and Proof records are inconsistent",
                    409,
                )
            if existing_proof is not None:
                if session.get("status") in {"verified", "proof_issuing"}:
                    session["status"] = "proof_issued"
                    session["failure_code"] = None
                    try:
                        repository.replace_session(session, record.etag)
                    except StorageConflict:
                        continue
                return 200, _proof_response(
                    existing_proof,
                    existing=True,
                    public_web_base_url=config.public_web_base_url,
                )
            if session.get("status") not in {"verified", "proof_issuing"}:
                raise ApiError(
                    "ERR_PROOF_CONFLICT",
                    "Session and Proof records are inconsistent",
                    409,
                )
            if _attempt < max_attempts - 1:
                time.sleep(0.01)
                continue
            try:
                proof_uuid = UUID(existing_proof_id.removeprefix("RP-"))
                raw_created_at = session["proof_created_at"]
                raw_signed_at = session["proof_signed_at"]
                algorithm = session["proof_signature_algorithm"]
                key_id = session["proof_key_id"]
                public_key = session["proof_public_key"]
                if not all(
                    isinstance(value, str) and value
                    for value in (raw_created_at, raw_signed_at, algorithm, key_id)
                ):
                    raise ValueError
                proof_created_at = datetime.fromisoformat(
                    raw_created_at.replace("Z", "+00:00")
                )
                proof_signed_at = datetime.fromisoformat(
                    raw_signed_at.replace("Z", "+00:00")
                )
                if not isinstance(public_key, dict):
                    raise ValueError
                signing_profile = SigningProfile(algorithm, key_id, public_key)
            except (TypeError, ValueError) as error:
                raise ApiError(
                    "ERR_PROOF_CONFLICT", "Proof reservation is invalid", 409
                ) from error
            except KeyError as error:
                raise ApiError(
                    "ERR_PROOF_CONFLICT", "Proof reservation is incomplete", 409
                ) from error
            reserved = record

        else:
            if session.get("status") == "evidence_uploaded":
                session["status"] = "validating"
                try:
                    record = repository.replace_session(session, record.etag)
                except StorageConflict:
                    continue
                write_audit_log(
                    repository,
                    "session_status_updated",
                    clock=clock,
                    session_id=session_id,
                    device_id=str(session["device_id"]),
                    message="Session status: validating",
                    detail={"status": "validating"},
                )
                session["status"] = "verified"
                try:
                    record = repository.replace_session(session, record.etag)
                except StorageConflict:
                    continue
                write_audit_log(
                    repository,
                    "session_status_updated",
                    clock=clock,
                    session_id=session_id,
                    device_id=str(session["device_id"]),
                    message="Session status: verified",
                    detail={"status": "verified"},
                )
            elif session.get("status") == "validating":
                time.sleep(0.01)
                continue
            elif session.get("status") != "verified":
                raise ApiError(
                    "ERR_EVIDENCE_NOT_ACCEPTED",
                    "Session does not contain accepted evidence",
                    409,
                )
            try:
                active_signer = signer or create_signer(config)
                signing_profile = active_signer.resolve_profile()
                signing_public_key = public_key_metadata(signing_profile)
            except ValueError as error:
                write_audit_log(
                    repository,
                    "error",
                    clock=clock,
                    session_id=session_id,
                    device_id=str(session["device_id"]),
                    message="Proof signing configuration failed",
                    detail={"failure_code": "ERR_SIGNATURE_FAILED"},
                )
                raise ApiError(
                    "ERR_SIGNATURE_FAILED",
                    "signing configuration is incomplete",
                    500,
                ) from error
            except SigningUnavailable as error:
                write_audit_log(
                    repository,
                    "error",
                    clock=clock,
                    session_id=session_id,
                    device_id=str(session["device_id"]),
                    message="Proof signing service unavailable",
                    detail={"failure_code": "ERR_SIGNATURE_FAILED"},
                )
                raise ApiError(
                    "ERR_SIGNATURE_FAILED",
                    "signing service is unavailable",
                    503,
                ) from error
            proof_uuid = uuid_factory()
            session["proof_id"] = f"RP-{proof_uuid}"
            proof_created_at = clock()
            proof_signed_at = proof_created_at
            session["proof_created_at"] = isoformat_milliseconds(proof_created_at)
            session["proof_signed_at"] = isoformat_milliseconds(proof_signed_at)
            session["proof_signature_algorithm"] = signing_profile.algorithm
            session["proof_key_id"] = signing_profile.key_id
            session["proof_public_key"] = signing_public_key
            try:
                reserved = repository.replace_session(session, record.etag)
            except StorageConflict:
                continue

        manifest = repository.load_manifest(session_id)
        if manifest is None:
            raise ApiError("ERR_MANIFEST_NOT_FOUND", "Manifest was not found", 404)
        try:
            active_signer = signer or create_signer(config)
            proof = build_proof_record(
                session=session,
                manifest=manifest,
                proof_uuid=proof_uuid,
                created_at=proof_created_at,
                public_web_base_url=config.public_web_base_url,
                signer=active_signer,
                signing_profile=signing_profile,
                signed_at=proof_signed_at,
            )
        except SigningUnavailable as error:
            write_audit_log(
                repository,
                "error",
                clock=clock,
                session_id=session_id,
                device_id=str(session["device_id"]),
                message="Proof signing service unavailable",
                detail={"failure_code": "ERR_SIGNATURE_FAILED"},
            )
            raise ApiError(
                "ERR_SIGNATURE_FAILED",
                "signing service is unavailable",
                503,
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            write_audit_log(
                repository,
                "error",
                clock=clock,
                session_id=session_id,
                device_id=str(session["device_id"]),
                message="Proof signing failed",
                detail={"failure_code": "ERR_SIGNATURE_FAILED"},
            )
            raise ApiError(
                "ERR_SIGNATURE_FAILED",
                "Proof signing failed",
                500,
            ) from error

        try:
            repository.save_proof(proof)
        except StorageConflict:
            stored = repository.load_proof(str(proof["proof_id"]))
            if (
                stored is None
                or stored.get("record_hash") != proof.get("record_hash")
                or stored.get("key_id") != proof.get("key_id")
                or stored.get("signature_algorithm")
                != proof.get("signature_algorithm")
            ):
                raise ApiError(
                    "ERR_PROOF_CONFLICT", "different Proof already exists", 409
                )
            proof = stored
        except StorageUnavailable as error:
            raise _storage_error() from error
        session["status"] = "proof_issued"
        session["failure_code"] = None
        try:
            repository.replace_session(session, reserved.etag)
        except StorageConflict:
            latest = repository.load_session_record(session_id)
            if latest is None or latest.value.get("proof_id") != proof["proof_id"]:
                raise ApiError(
                    "ERR_PROOF_CONFLICT", "Session changed during Proof issue", 409
                )
        try:
            repository.save_qr(
                str(proof["proof_id"]),
                generate_qr_png(str(proof["verification_url"])),
            )
        except StorageUnavailable as error:
            raise _storage_error() from error
        write_audit_log(
            repository,
            "session_status_updated",
            clock=clock,
            session_id=session_id,
            proof_id=str(proof["proof_id"]),
            device_id=str(session["device_id"]),
            message="Session status: proof_issued",
            detail={"status": "proof_issued"},
        )
        write_audit_log(
            repository,
            "proof_issued",
            clock=clock,
            session_id=session_id,
            proof_id=str(proof["proof_id"]),
            device_id=str(session["device_id"]),
            message="Proof issued",
        )
        return 201, _proof_response(
            proof,
            existing=False,
            public_web_base_url=config.public_web_base_url,
        )
    raise ApiError("ERR_PROOF_CONFLICT", "Proof issue did not converge", 409)


def verify_proof(
    proof_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    verifier: Verifier | None = None,
) -> tuple[int, dict[str, object]]:
    if not isinstance(proof_id, str) or not proof_id:
        raise ApiError("ERR_INVALID_REQUEST", "proof_id is required", 400)
    if not config.use_azure_key_vault and not config.stub_signing_secret:
        raise ApiError(
            "ERR_SIGNATURE_FAILED",
            "stub signing configuration is incomplete",
            500,
        )

    try:
        proof = repository.load_proof(proof_id)
    except ValueError as error:
        raise ApiError(
            "ERR_PROOF_INVALID",
            "Proof Record is not valid for public display",
            422,
        ) from error
    if proof is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", "Proof was not found", 404)

    session_id = proof.get("session_id")
    try:
        session = (
            repository.load_session(session_id)
            if isinstance(session_id, str)
            else None
        )
        manifest = (
            repository.load_manifest(session_id)
            if isinstance(session_id, str)
            else None
        )
        device_id = proof.get("device_id")
        device = (
            repository.load_device(device_id)
            if isinstance(device_id, str)
            else None
        )
    except ValueError:
        session = None
        manifest = None
        device = None
    evidence_verification: EvidenceVerification | None = None
    if manifest is not None:
        try:
            evidence_verification = repository.verify_evidence_files(manifest)
        except BlobVerificationError as error:
            evidence_verification = EvidenceVerification(
                verified=False,
                image_hash=(
                    False if error.evidence_name == "image" else None
                ),
                audio_hash=(
                    False if error.evidence_name == "audio" else None
                ),
            )
        except StorageUnavailable:
            evidence_verification = None
    try:
        active_verifier = verifier
        if (
            proof.get("signature_algorithm") != "STUB-HS256"
            and active_verifier is None
        ):
            try:
                active_verifier = create_verifier(config)
            except SigningUnavailable:
                active_verifier = None
        result = verify_proof_record(
            requested_proof_id=proof_id,
            proof=proof,
            session=session,
            manifest=manifest,
            signing_secret=config.stub_signing_secret,
            signature_key_id=config.signature_key_id,
            verifier=active_verifier,
            evidence_verification=evidence_verification,
            device=device,
        )
        write_audit_log(
            repository,
            "proof_verified",
            proof_id=proof_id,
            session_id=session_id if isinstance(session_id, str) else None,
            device_id=(
                str(proof.get("device_id"))
                if isinstance(proof.get("device_id"), str)
                else None
            ),
            message=f"Proof verification result: {result['status']}",
        )
        return 200, result
    except SigningUnavailable as error:
        raise ApiError(
            "ERR_SIGNATURE_UNAVAILABLE",
            "signature verification service is unavailable",
            503,
        ) from error


def get_public_proof(
    proof_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
) -> tuple[int, dict[str, object]]:
    if not isinstance(proof_id, str) or not proof_id:
        raise ApiError("ERR_INVALID_REQUEST", "proof_id is required", 400)
    try:
        proof = repository.load_proof(proof_id)
    except ValueError as error:
        raise ApiError(
            "ERR_PROOF_INVALID",
            "Proof Record is not valid for QR generation",
            422,
        ) from error
    if proof is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", "Proof was not found", 404)
    try:
        session_id = proof.get("session_id")
        manifest = (
            repository.load_manifest(session_id)
            if isinstance(session_id, str)
            else None
        )
        projection = public_proof_projection(
            proof,
            config.public_web_base_url,
            manifest,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(
            "ERR_PROOF_INVALID",
            "Proof Record is not valid for public display",
            422,
        ) from error
    return 200, projection


def get_proof_qr(
    proof_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
) -> tuple[int, bytes]:
    if not isinstance(proof_id, str) or not proof_id:
        raise ApiError("ERR_INVALID_REQUEST", "proof_id is required", 400)
    try:
        proof = repository.load_proof(proof_id)
    except ValueError as error:
        raise ApiError("ERR_INVALID_REQUEST", str(error), 400) from error
    if proof is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", "Proof was not found", 404)
    stored = repository.load_qr(proof_id)
    if stored is not None:
        return 200, stored
    url = verification_page_url(config.public_web_base_url, proof_id)
    png = generate_qr_png(url)
    repository.save_qr(proof_id, png)
    return 200, png


def list_devices(
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
) -> tuple[int, dict[str, object]]:
    devices = repository.list_devices()
    existing = {
        str(device.get("device_id"))
        for device in devices
        if isinstance(device.get("device_id"), str)
    }
    for device_id in sorted(config.allowed_device_ids - existing):
        require_active_device(
            device_id,
            config=config,
            repository=repository,
            clock=clock,
        )
    devices = repository.list_devices()
    public_devices = [
        {
            "device_id": device.get("device_id"),
            "display_name": device.get("display_name"),
            "status": device.get("status"),
            "last_seen_at": device.get("last_seen_at"),
            "public_note": device.get("public_note"),
        }
        for device in devices
    ]
    return 200, {"devices": public_devices}


def get_session(
    session_id: str,
    *,
    repository: StorageRepository,
) -> tuple[int, dict[str, object]]:
    if not session_id:
        raise ApiError("ERR_INVALID_REQUEST", "session_id is required", 400)
    session = repository.load_session(session_id)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Session was not found", 404)
    return 200, {
        "session_id": session.get("session_id"),
        "device_id": session.get("device_id"),
        "status": session.get("status"),
        "challenge": {
            "instruction_ja": session.get("challenge_text"),
            "button_count": session.get("button_count"),
            "voice_code": session.get("voice_code"),
            "time_limit_seconds": session.get("time_limit_seconds"),
        },
        "created_at": session.get("created_at"),
        "expires_at": session.get("expires_at"),
        "proof_id": session.get("proof_id"),
        "failure_code": session.get("failure_code"),
        "evidence_bytes_verified": session.get("evidence_bytes_verified"),
    }


def get_admin_proof(
    proof_id: str,
    *,
    repository: StorageRepository,
) -> tuple[int, dict[str, object]]:
    if not proof_id:
        raise ApiError("ERR_INVALID_REQUEST", "proof_id is required", 400)
    proof = repository.load_proof(proof_id)
    if proof is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", "Proof was not found", 404)
    session_id = proof.get("session_id")
    manifest = (
        repository.load_manifest(session_id)
        if isinstance(session_id, str)
        else None
    )
    return 200, {"proof": proof, "manifest": manifest}


def get_verification_page(
    proof_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
) -> tuple[int, str]:
    if not isinstance(proof_id, str) or not proof_id:
        return 404, render_verification_page(
            proof_id=proof_id or "Unknown",
            state="not_found",
        )
    try:
        proof = repository.load_proof(proof_id)
    except ValueError:
        return 503, render_verification_page(
            proof_id=proof_id,
            state="rejected",
        )
    if proof is None:
        return 404, render_verification_page(
            proof_id=proof_id,
            state="not_found",
        )

    try:
        session_id = proof.get("session_id")
        manifest = (
            repository.load_manifest(session_id)
            if isinstance(session_id, str)
            else None
        )
        projection = public_proof_projection(
            proof,
            config.public_web_base_url,
            manifest,
        )
    except (KeyError, TypeError, ValueError):
        return 503, render_verification_page(
            proof_id=proof_id,
            state="rejected",
        )

    try:
        _, verification = verify_proof(
            proof_id,
            config=config,
            repository=repository,
        )
    except ApiError:
        return 503, render_verification_page(
            proof_id=proof_id,
            state="rejected",
            proof=projection,
        )

    state = verification_state(verification)
    return 200, render_verification_page(
        proof_id=proof_id,
        state=state,
        proof=projection,
        verification=verification,
    )
