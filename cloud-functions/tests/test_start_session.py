from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import start_session
from reality_cloud.storage import LocalJsonRepository


def test_start_session_saves_allowlisted_device(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )
    random_values = iter([1, 7])

    status, response = start_session(
        {"device_id": "raspi-anchor-01"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc),
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: next(random_values),
    )

    assert status == 201
    saved = repository.load_session(str(response["session_id"]))
    assert saved is not None
    assert saved["status"] == "waiting_device"
    assert saved["voice_code"] == "0007"


def test_start_session_keeps_azure_upload_targets_out_of_http_response(
    config: CloudConfig,
    repository: LocalJsonRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        repository,
        "create_upload_targets",
        "create_upload_targets",
        lambda session_id, expires_at: calls.append(
            (session_id, expires_at)
        ),
    )
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    _, response = start_session(
        {"device_id": "raspi-anchor-01"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc),
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: 0,
    )

    assert "upload" not in response
    assert calls == []


@pytest.mark.parametrize(
    ("payload", "status_code"),
    [
        ({}, 400),
        ({"device_id": ""}, 400),
        ({"device_id": "unregistered"}, 403),
        ([], 400),
    ],
)
def test_start_session_rejects_invalid_requests(
    payload: object,
    status_code: int,
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    with pytest.raises(ApiError) as captured:
        start_session(
            payload,
            config=config,
            repository=repository,
            uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
            randbelow=lambda limit: 0,
        )
    assert captured.value.status_code == status_code


def test_azure_http_start_session_can_be_called_directly(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOWED_DEVICE_IDS", "raspi-anchor-01")
    monkeypatch.setenv("DEVICE_API_KEY", "test-device-api-key")
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/api/sessions/start",
        headers={
            "content-type": "application/json",
            "X-Device-Api-Key": "test-device-api-key",
        },
        params={},
        route_params={},
        body=json.dumps({"device_id": "raspi-anchor-01"}).encode(),
    )

    response = function_app.start_session_http(request)

    assert response.status_code == 201
    payload = json.loads(response.get_body())
    assert payload["device_id"] == "raspi-anchor-01"
