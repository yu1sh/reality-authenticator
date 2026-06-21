from __future__ import annotations

import json

import azure.functions as func
import pytest

import function_app
from reality_cloud.auth import require_device_api_key
from reality_cloud.errors import ApiError


def test_device_api_key_accepts_matching_value() -> None:
    require_device_api_key(
        {"X-Device-Api-Key": "test-key"},
        "test-key",
    )


@pytest.mark.parametrize(
    ("configured", "supplied", "code", "status"),
    [
        (None, "test-key", "ERR_AUTH_NOT_CONFIGURED", 503),
        ("test-key", None, "ERR_UNAUTHORIZED", 401),
        ("test-key", "wrong-key", "ERR_UNAUTHORIZED", 401),
    ],
)
def test_device_api_key_rejects_invalid_configuration_or_value(
    configured: str | None,
    supplied: str | None,
    code: str,
    status: int,
) -> None:
    headers = {"X-Device-Api-Key": supplied} if supplied is not None else {}
    with pytest.raises(ApiError) as captured:
        require_device_api_key(headers, configured)
    assert captured.value.code == code
    assert captured.value.status_code == status


@pytest.mark.parametrize(
    ("operation", "url", "body"),
    [
        (
            function_app.start_session_http,
            "http://localhost/api/sessions/start",
            {"device_id": "raspi-anchor-01"},
        ),
        (
            function_app.ingest_evidence_http,
            "http://localhost/api/evidence/ingest",
            {"session_id": "session-1"},
        ),
        (
            function_app.issue_proof_http,
            "http://localhost/api/proofs/issue",
            {"session_id": "session-1"},
        ),
    ],
)
def test_private_http_endpoints_fail_closed_without_configuration(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
    url: str,
    body: dict[str, object],
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    request = func.HttpRequest(
        method="POST",
        url=url,
        headers={"content-type": "application/json"},
        params={},
        route_params={},
        body=json.dumps(body).encode(),
    )

    response = operation(request)

    assert response.status_code == 503
    assert json.loads(response.get_body())["error"]["code"] == (
        "ERR_AUTH_NOT_CONFIGURED"
    )


def test_public_verification_route_does_not_require_device_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEVICE_API_KEY", raising=False)
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/api/proofs/missing/verify",
        headers={},
        params={},
        route_params={"proof_id": "missing"},
        body=b"",
    )

    response = function_app.verify_proof_http(request)

    assert response.status_code != 401
    assert response.status_code != 503
