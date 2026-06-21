"""Registered Anchor Device behavior."""

from __future__ import annotations

from .challenge import Clock, isoformat_milliseconds, utc_now
from .config import CloudConfig
from .errors import ApiError
from .storage_contract import StorageRepository


def default_device(device_id: str, *, clock: Clock = utc_now) -> dict[str, object]:
    return {
        "device_id": device_id,
        "display_name": device_id,
        "status": "active",
        "created_at": isoformat_milliseconds(clock()),
        "last_seen_at": None,
        "iot_hub_device_id": device_id,
        "public_note": "",
    }


def require_active_device(
    device_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
) -> dict[str, object]:
    device = repository.load_device(device_id)
    if device is None and device_id in config.allowed_device_ids:
        device = default_device(device_id, clock=clock)
        repository.save_device(device)
    if device is None:
        raise ApiError("ERR_DEVICE_NOT_ALLOWED", "device is not registered", 403)
    if device.get("status") != "active":
        raise ApiError("ERR_DEVICE_DISABLED", "device is disabled", 403)
    return device


def mark_device_seen(
    device_id: str,
    *,
    config: CloudConfig,
    repository: StorageRepository,
    clock: Clock = utc_now,
) -> dict[str, object]:
    device = require_active_device(
        device_id,
        config=config,
        repository=repository,
        clock=clock,
    )
    device["last_seen_at"] = isoformat_milliseconds(clock())
    repository.save_device(device)
    return device
