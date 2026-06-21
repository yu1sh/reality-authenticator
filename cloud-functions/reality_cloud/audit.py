"""AuditLog construction and persistence."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from .challenge import Clock, isoformat_milliseconds, utc_now
from .storage_contract import StorageRepository


def write_audit_log(
    repository: StorageRepository,
    event_type: str,
    *,
    clock: Clock = utc_now,
    session_id: str | None = None,
    proof_id: str | None = None,
    device_id: str | None = None,
    message: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> None:
    repository.save_audit_log(
        {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "session_id": session_id,
            "proof_id": proof_id,
            "device_id": device_id,
            "created_at": isoformat_milliseconds(clock()),
            "message": message,
            "detail": dict(detail or {}),
        }
    )
