"""IoT Hub telemetry orchestration."""

from __future__ import annotations

from .audit import write_audit_log
from .challenge import Clock, utc_now
from .config import CloudConfig
from .devices import mark_device_seen
from .errors import ApiError
from .handlers import ingest_evidence, issue_proof
from .iot import TelemetryEnvelope
from .storage_contract import StorageConflict, StorageRepository

_STATUS_ORDER = {
    "created": 0,
    "challenge_issued": 1,
    "waiting_device": 2,
    "capturing": 3,
    "evidence_uploaded": 4,
    "validating": 5,
    "verified": 6,
    "proof_issued": 7,
}


def _set_session_status(
    repository: StorageRepository,
    session_id: str,
    status: str,
    *,
    failure_code: str | None = None,
    clock: Clock = utc_now,
) -> dict[str, object]:
    for _ in range(3):
        record = repository.load_session_record(session_id)
        if record is None:
            raise ApiError("ERR_SESSION_NOT_FOUND", "Session was not found", 404)
        session = record.value
        current = session.get("status")
        if current == status:
            return session
        if status != "failed":
            current_order = _STATUS_ORDER.get(str(current))
            target_order = _STATUS_ORDER.get(status)
            if current_order is None or target_order is None:
                raise ApiError(
                    "ERR_STORAGE_CONFLICT",
                    "Session status is invalid",
                    409,
                )
            if current_order > target_order:
                return session
            if current_order + 1 != target_order:
                raise ApiError(
                    "ERR_STORAGE_CONFLICT",
                    "Session status transition is invalid",
                    409,
                )
        session["status"] = status
        session["failure_code"] = failure_code
        try:
            updated = repository.replace_session(session, record.etag).value
            write_audit_log(
                repository,
                "session_status_updated",
                clock=clock,
                session_id=session_id,
                device_id=str(session.get("device_id") or ""),
                message=f"Session status: {status}",
                detail={"status": status, "failure_code": failure_code},
            )
            return updated
        except StorageConflict:
            continue
    raise ApiError("ERR_STORAGE_CONFLICT", "Session status changed", 409)


def process_telemetry(
    envelope: TelemetryEnvelope,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
) -> dict[str, object]:
    mark_device_seen(
        envelope.device_id,
        config=config,
        repository=repository,
        clock=clock,
    )

    if envelope.message_type == "heartbeat":
        write_audit_log(
            repository,
            "device_heartbeat",
            clock=clock,
            device_id=envelope.device_id,
            message="Device heartbeat received",
        )
        return {"accepted": True, "message_type": "heartbeat"}

    if envelope.message_type == "device_status":
        session_id = envelope.payload.get("session_id")
        device_status = envelope.payload.get("status")
        if not isinstance(session_id, str) or not isinstance(device_status, str):
            raise ApiError(
                "ERR_INVALID_TELEMETRY",
                "device status telemetry is incomplete",
                400,
            )
        if device_status not in {
            "challenge_received",
            "capturing",
            "failed",
            "duplicate_ignored",
        }:
            raise ApiError(
                "ERR_INVALID_TELEMETRY",
                "device status telemetry is unsupported",
                400,
            )
        session = repository.load_session(session_id)
        if session is None:
            raise ApiError("ERR_SESSION_NOT_FOUND", "Session was not found", 404)
        if session.get("device_id") != envelope.device_id:
            raise ApiError("ERR_DEVICE_MISMATCH", "device_id does not match", 403)
        if device_status in {"challenge_received", "capturing"}:
            _set_session_status(
                repository,
                session_id,
                "capturing",
                clock=clock,
            )
        elif device_status == "failed":
            failure_code = envelope.payload.get("failure_code")
            _set_session_status(
                repository,
                session_id,
                "failed",
                failure_code=(
                    failure_code
                    if isinstance(failure_code, str)
                    else "ERR_CAPTURE_FAILED"
                ),
                clock=clock,
            )
        write_audit_log(
            repository,
            "device_status",
            clock=clock,
            session_id=session_id,
            device_id=envelope.device_id,
            message=f"Device status: {device_status}",
        )
        return {"accepted": True, "message_type": "device_status"}

    if envelope.message_type != "evidence_manifest":
        raise ApiError(
            "ERR_INVALID_TELEMETRY",
            "unsupported telemetry message_type",
            400,
        )
    manifest = envelope.payload.get("manifest")
    if not isinstance(manifest, dict):
        raise ApiError(
            "ERR_INVALID_TELEMETRY",
            "evidence telemetry does not contain a Manifest",
            400,
        )
    if manifest.get("device_id") != envelope.device_id:
        raise ApiError("ERR_DEVICE_MISMATCH", "device_id does not match", 403)
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str):
        raise ApiError("ERR_INVALID_MANIFEST", "session_id is required", 400)

    _set_session_status(repository, session_id, "capturing", clock=clock)
    ingest_evidence(manifest, repository=repository, clock=clock)
    issue_status, issued = issue_proof(
        {"session_id": session_id},
        config=config,
        repository=repository,
        clock=clock,
    )
    return {
        "accepted": True,
        "message_type": "evidence_manifest",
        "issue_status": issue_status,
        **issued,
    }
