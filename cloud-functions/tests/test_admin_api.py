from __future__ import annotations

import json

import azure.functions as func
import pytest

import function_app


def test_devices_api_requires_admin_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    request = func.HttpRequest(
        method="GET",
        url="http://localhost/api/devices",
        headers={},
        params={},
        route_params={},
        body=b"",
    )

    response = function_app.list_devices_http(request)

    assert response.status_code == 401


def test_devices_api_returns_registered_devices(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    request = func.HttpRequest(
        method="GET",
        url="http://localhost/api/devices",
        headers={"X-Admin-Api-Key": "admin-secret"},
        params={},
        route_params={},
        body=b"",
    )

    response = function_app.list_devices_http(request)
    payload = json.loads(response.get_body())

    assert response.status_code == 200
    assert payload["devices"][0]["device_id"] == "raspi-anchor-01"
