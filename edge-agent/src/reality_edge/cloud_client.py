"""HTTP client for the local Reality Authenticator Cloud API."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CloudClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


OpenFunction = Callable[..., Any]


def _require_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise CloudClientError(
            "ERR_INVALID_CLOUD_RESPONSE",
            f"{field_name} is invalid",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CloudClientError(
            "ERR_INVALID_CLOUD_RESPONSE",
            f"{field_name} is invalid",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CloudClientError(
            "ERR_INVALID_CLOUD_RESPONSE",
            f"{field_name} is invalid",
        )
    return value


class CloudClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        device_api_key: str,
        timeout_seconds: float = 5.0,
        opener: OpenFunction = urlopen,
    ) -> None:
        if not device_api_key:
            raise ValueError("DEVICE_API_KEY is required for cloud sync")
        self.api_base_url = api_base_url.rstrip("/")
        self.device_api_key = device_api_key
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def _post(
        self,
        path: str,
        payload: dict[str, object] | None,
        *,
        authenticated: bool,
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["X-Device-Api-Key"] = self.device_api_key
        request = Request(
            f"{self.api_base_url}/{path.lstrip('/')}",
            data=(
                json.dumps(
                    payload or {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            headers=headers,
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            try:
                body = response.read()
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except HTTPError as error:
            self._raise_http_error(error)
        except (TimeoutError, socket.timeout, URLError, OSError) as error:
            raise CloudClientError(
                "ERR_CLOUD_UNAVAILABLE",
                "Cloud API is unavailable",
            ) from error

        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "Cloud API returned invalid JSON",
            ) from error
        if not isinstance(value, dict):
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "Cloud API response must be a JSON object",
            )
        return value

    @staticmethod
    def _raise_http_error(error: HTTPError) -> None:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            error_value = payload.get("error")
            if not isinstance(error_value, dict):
                raise ValueError
            code = error_value.get("code")
            message = error_value.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, AttributeError):
            code = "ERR_CLOUD_HTTP"
            message = f"Cloud API returned HTTP {error.code}"
        raise CloudClientError(code, message) from error

    def start_session(self, device_id: str) -> dict[str, object]:
        response = self._post(
            "sessions/start",
            {"device_id": device_id},
            authenticated=True,
        )
        session_id = response.get("session_id")
        challenge = response.get("challenge")
        expires_at = response.get("expires_at")
        if (
            not isinstance(session_id, str)
            or not session_id
            or response.get("device_id") != device_id
            or not isinstance(challenge, dict)
        ):
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "StartSession response is incomplete",
            )
        expected_types = {
            "instruction_ja": str,
            "button_count": int,
            "voice_code": str,
            "time_limit_seconds": int,
        }
        for name, expected_type in expected_types.items():
            value = challenge.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, expected_type)
                or (expected_type is str and not value)
            ):
                raise CloudClientError(
                    "ERR_INVALID_CLOUD_RESPONSE",
                    "StartSession challenge is invalid",
                )
        if int(challenge["button_count"]) < 1:
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "StartSession button_count is invalid",
            )
        if int(challenge["time_limit_seconds"]) < 1:
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "StartSession time_limit_seconds is invalid",
            )
        voice_code = str(challenge["voice_code"])
        if len(voice_code) != 4 or not voice_code.isdigit():
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "StartSession voice_code is invalid",
            )
        _require_timestamp(expires_at, "StartSession expires_at")
        upload = response.get("upload")
        if upload is not None:
            self._validate_upload(upload)
        return response

    @staticmethod
    def _validate_upload(upload: object) -> None:
        if not isinstance(upload, dict) or upload.get("mode") != "sas_url":
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE", "StartSession upload is invalid"
            )
        _require_timestamp(upload.get("expires_at"), "StartSession upload.expires_at")
        for name in ("image", "audio"):
            target = upload.get(name)
            if not isinstance(target, dict) or not all(
                isinstance(target.get(field), str) and target.get(field)
                for field in ("blob_path", "url", "content_type")
            ):
                raise CloudClientError(
                    "ERR_INVALID_CLOUD_RESPONSE",
                    f"StartSession upload.{name} is invalid",
                )

    def ingest_evidence(self, manifest: dict[str, object]) -> dict[str, object]:
        response = self._post("evidence/ingest", manifest, authenticated=True)
        if response.get("accepted") is not True:
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "IngestEvidence did not accept evidence",
            )
        return response

    def issue_proof(self, session_id: str) -> dict[str, object]:
        response = self._post(
            "proofs/issue",
            {"session_id": session_id},
            authenticated=True,
        )
        if (
            response.get("issued") is not True
            or not isinstance(response.get("proof_id"), str)
            or not isinstance(response.get("verification_url"), str)
        ):
            raise CloudClientError(
                "ERR_PROOF_NOT_ISSUED",
                "IssueProof response is incomplete",
            )
        return response

    def verify_proof(self, proof_id: str) -> dict[str, object]:
        response = self._post(
            f"proofs/{proof_id}/verify",
            None,
            authenticated=False,
        )
        if (
            response.get("proof_id") != proof_id
            or not isinstance(response.get("valid"), bool)
            or not isinstance(response.get("checks"), dict)
        ):
            raise CloudClientError(
                "ERR_INVALID_CLOUD_RESPONSE",
                "VerifyProof response is incomplete",
            )
        return response
