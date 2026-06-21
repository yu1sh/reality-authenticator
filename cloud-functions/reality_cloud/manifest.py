"""Evidence Manifest validation."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Mapping

from .errors import ApiError

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg"})
_AUDIO_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav"})


def _error(code: str, message: str, status: int = 400) -> ApiError:
    return ApiError(code, message, status)


def parse_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise _error("ERR_INVALID_MANIFEST", f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _error(
            "ERR_INVALID_MANIFEST",
            f"{field_name} must be an ISO 8601 timestamp",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error(
            "ERR_INVALID_MANIFEST",
            f"{field_name} must include a UTC offset",
        )
    return parsed


def _validate_blob_path(value: object, session_id: str, filename: str) -> None:
    if not isinstance(value, str) or not value:
        raise _error("ERR_INVALID_MANIFEST", f"{filename} blob_path is required")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise _error("ERR_INVALID_MANIFEST", f"{filename} blob_path is invalid")
    expected = PurePosixPath("evidence") / session_id / filename
    if path != expected:
        raise _error(
            "ERR_INVALID_MANIFEST",
            f"{filename} blob_path must be {expected}",
        )


def _validate_file(
    *,
    files: Mapping[str, object],
    key: str,
    filename: str,
    session_id: str,
    allowed_content_types: frozenset[str],
) -> None:
    metadata = files.get(key)
    if not isinstance(metadata, dict):
        raise _error("ERR_FILE_MISSING", f"{key} metadata is required")
    _validate_blob_path(metadata.get("blob_path"), session_id, filename)

    digest = metadata.get("sha256")
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        raise _error("ERR_INVALID_MANIFEST", f"{key} sha256 is invalid")

    size = metadata.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise _error("ERR_INVALID_MANIFEST", f"{key} size_bytes must be positive")

    content_type = metadata.get("content_type")
    if content_type not in allowed_content_types:
        raise _error("ERR_INVALID_MANIFEST", f"{key} content_type is invalid")


def validate_manifest(
    manifest: Mapping[str, object],
    session: Mapping[str, object],
    *,
    now: datetime,
) -> None:
    if manifest.get("schema_version") != "1.0":
        raise _error("ERR_SCHEMA_VERSION", "schema_version must be 1.0")
    if manifest.get("device_id") != session.get("device_id"):
        raise _error("ERR_DEVICE_MISMATCH", "device_id does not match Session", 403)

    session_id = str(session["session_id"])
    if manifest.get("session_id") != session_id:
        raise _error("ERR_INVALID_MANIFEST", "session_id does not match Session")

    challenge = manifest.get("challenge")
    if challenge is not None:
        expected_challenge = {
            "instruction_ja": session.get("challenge_text"),
            "button_count": session.get("button_count"),
            "voice_code": session.get("voice_code"),
            "time_limit_seconds": session.get("time_limit_seconds"),
        }
        if challenge != expected_challenge:
            raise _error(
                "ERR_INVALID_MANIFEST",
                "challenge does not match Session",
            )

    created_at = parse_timestamp(session.get("created_at"), "Session created_at")
    expires_at = parse_timestamp(session.get("expires_at"), "Session expires_at")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    if now > expires_at:
        raise _error("ERR_SESSION_EXPIRED", "Session has expired", 409)

    edge_started_at = parse_timestamp(
        manifest.get("edge_started_at"), "edge_started_at"
    )
    edge_finished_at = parse_timestamp(
        manifest.get("edge_finished_at"), "edge_finished_at"
    )
    if edge_started_at < created_at or edge_finished_at < edge_started_at:
        raise _error("ERR_INVALID_MANIFEST", "capture time range is invalid")
    if edge_finished_at > expires_at:
        raise _error("ERR_SESSION_EXPIRED", "capture finished after Session expiry", 409)

    expected_button_count = session.get("button_count")
    events = manifest.get("button_events")
    if not isinstance(events, list) or len(events) != expected_button_count:
        raise _error("ERR_BUTTON_COUNT", "button event count does not match challenge")
    for expected_index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("index") != expected_index:
            raise _error("ERR_BUTTON_COUNT", "button event indexes are invalid")
        event_time = parse_timestamp(
            event.get("timestamp"), f"button_events[{expected_index - 1}].timestamp"
        )
        if not edge_started_at <= event_time <= edge_finished_at:
            raise _error("ERR_BUTTON_COUNT", "button event is outside capture range")
        if not created_at <= event_time <= expires_at:
            raise _error("ERR_BUTTON_COUNT", "button event is outside Session range")

    sensors = manifest.get("sensors")
    if not isinstance(sensors, dict) or len(sensors) < 2:
        raise _error("ERR_INVALID_MANIFEST", "at least two sensors are required")
    for name, value in sensors.items():
        if (
            not isinstance(name, str)
            or not name
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise _error("ERR_INVALID_MANIFEST", "sensor values must be finite numbers")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise _error("ERR_FILE_MISSING", "files metadata is required")
    _validate_file(
        files=files,
        key="image",
        filename="image.jpg",
        session_id=session_id,
        allowed_content_types=_IMAGE_CONTENT_TYPES,
    )
    _validate_file(
        files=files,
        key="audio",
        filename="audio.wav",
        session_id=session_id,
        allowed_content_types=_AUDIO_CONTENT_TYPES,
    )

    edge_version = manifest.get("edge_version")
    if not isinstance(edge_version, str) or not edge_version:
        raise _error("ERR_INVALID_MANIFEST", "edge_version is required")
