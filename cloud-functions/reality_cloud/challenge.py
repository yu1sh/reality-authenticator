"""Session and challenge generation."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from .config import CloudConfig

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]
RandBelow = Callable[[int], int]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_milliseconds(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def create_session(
    *,
    device_id: str,
    config: CloudConfig,
    clock: Clock = utc_now,
    uuid_factory: UuidFactory = uuid4,
    randbelow: RandBelow = secrets.randbelow,
) -> tuple[dict[str, object], dict[str, object]]:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")

    session_id = str(uuid_factory())
    challenge_nonce = str(uuid_factory())
    button_count = randbelow(3) + 1
    voice_code = f"{randbelow(10_000):04d}"
    expires_at = now + timedelta(
        seconds=config.time_limit_seconds + config.grace_seconds
    )
    instruction = (
        f"{config.time_limit_seconds}秒以内に物理ボタンを"
        f"{button_count}回押し、{voice_code}と読み上げてください。"
    )

    session = {
        "session_id": session_id,
        "device_id": device_id,
        "status": "created",
        "challenge_nonce": challenge_nonce,
        "challenge_text": instruction,
        "button_count": button_count,
        "voice_code": voice_code,
        "time_limit_seconds": config.time_limit_seconds,
        "created_at": isoformat_milliseconds(now),
        "expires_at": isoformat_milliseconds(expires_at),
        "failure_code": None,
    }
    response = {
        "session_id": session_id,
        "device_id": device_id,
        "challenge": {
            "instruction_ja": instruction,
            "button_count": button_count,
            "voice_code": voice_code,
            "time_limit_seconds": config.time_limit_seconds,
        },
        "expires_at": session["expires_at"],
    }
    return session, response
