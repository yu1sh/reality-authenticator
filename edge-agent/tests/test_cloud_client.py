from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from reality_edge.cloud_client import CloudClient, CloudClientError


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode()
        self.closed = False

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True


def test_client_sends_auth_header_and_validates_start_response() -> None:
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "session_id": "session-1",
                "device_id": "device-1",
                "challenge": {
                    "instruction_ja": "challenge",
                    "button_count": 2,
                    "voice_code": "0007",
                    "time_limit_seconds": 10,
                },
                "expires_at": "2026-06-09T01:00:15.000+00:00",
            }
        )

    client = CloudClient(
        api_base_url="http://localhost:7071/api/",
        device_api_key="test-key",
        opener=opener,
    )

    response = client.start_session("device-1")

    request, timeout = requests[0]
    assert response["session_id"] == "session-1"
    assert request.full_url == "http://localhost:7071/api/sessions/start"
    assert request.get_header("X-device-api-key") == "test-key"
    assert timeout == 5.0


def test_verify_request_is_anonymous() -> None:
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        return FakeResponse(
            {
                "proof_id": "RP-1",
                "valid": True,
                "checks": {"signature": True},
            }
        )

    client = CloudClient(
        api_base_url="http://localhost:7071/api",
        device_api_key="test-key",
        opener=opener,
    )

    client.verify_proof("RP-1")

    assert requests[0].get_header("X-device-api-key") is None


def test_http_error_preserves_cloud_error_code() -> None:
    def opener(request, *, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                b'{"error":{"code":"ERR_UNAUTHORIZED","message":"denied"}}'
            ),
        )

    client = CloudClient(
        api_base_url="http://localhost:7071/api",
        device_api_key="wrong",
        opener=opener,
    )

    with pytest.raises(CloudClientError) as captured:
        client.start_session("device-1")
    assert captured.value.code == "ERR_UNAUTHORIZED"


@pytest.mark.parametrize(
    "error",
    [
        URLError("connection refused"),
        TimeoutError(),
    ],
)
def test_connection_failures_map_to_cloud_unavailable(error: Exception) -> None:
    def opener(request, *, timeout):
        raise error

    client = CloudClient(
        api_base_url="http://localhost:7071/api",
        device_api_key="test-key",
        opener=opener,
    )

    with pytest.raises(CloudClientError) as captured:
        client.start_session("device-1")
    assert captured.value.code == "ERR_CLOUD_UNAVAILABLE"


def test_invalid_json_is_rejected() -> None:
    class InvalidResponse(FakeResponse):
        def __init__(self) -> None:
            self.body = b"not-json"
            self.closed = False

    client = CloudClient(
        api_base_url="http://localhost:7071/api",
        device_api_key="test-key",
        opener=lambda request, timeout: InvalidResponse(),
    )

    with pytest.raises(CloudClientError) as captured:
        client.start_session("device-1")
    assert captured.value.code == "ERR_INVALID_CLOUD_RESPONSE"
