"""API key authentication for private Edge and administrator endpoints."""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from .errors import ApiError

DEVICE_API_KEY_HEADER = "X-Device-Api-Key"
ADMIN_API_KEY_HEADER = "X-Admin-Api-Key"


def require_device_api_key(
    headers: Mapping[str, str],
    configured_key: str | None,
) -> None:
    if not configured_key:
        raise ApiError(
            "ERR_AUTH_NOT_CONFIGURED",
            "device authentication is not configured",
            503,
        )

    supplied_key = headers.get(DEVICE_API_KEY_HEADER)
    if not supplied_key or not hmac.compare_digest(supplied_key, configured_key):
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "device authentication failed",
            401,
        )


def require_admin_api_key(
    headers: Mapping[str, str],
    configured_key: str | None,
) -> None:
    if not configured_key:
        raise ApiError(
            "ERR_AUTH_NOT_CONFIGURED",
            "administrator authentication is not configured",
            503,
        )

    supplied_key = headers.get(ADMIN_API_KEY_HEADER)
    if not supplied_key or not hmac.compare_digest(supplied_key, configured_key):
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "administrator authentication failed",
            401,
        )
