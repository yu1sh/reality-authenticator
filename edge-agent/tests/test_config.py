from __future__ import annotations

import pytest

from reality_edge.config import EdgeConfig


def test_cloud_settings_are_loaded_and_urls_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://localhost:7071/api/")
    monkeypatch.setenv("VERIFY_BASE_URL", "http://localhost:7071/")
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")
    monkeypatch.setenv("CLOUD_SYNC_ENABLED", "yes")

    config = EdgeConfig.from_environment()

    assert config.api_base_url == "http://localhost:7071/api"
    assert config.verify_base_url == "http://localhost:7071"
    assert config.device_api_key == "test-key"
    assert config.cloud_sync_enabled is True


@pytest.mark.parametrize("value", ["sometimes", "2", ""])
def test_invalid_cloud_sync_boolean_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("CLOUD_SYNC_ENABLED", value)
    with pytest.raises(ValueError, match="CLOUD_SYNC_ENABLED"):
        EdgeConfig.from_environment()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("API_BASE_URL", "localhost:7071/api"),
        ("VERIFY_BASE_URL", "file:///tmp/verify"),
        ("VERIFY_BASE_URL", "http://localhost:7071?secret=value"),
        ("VERIFY_BASE_URL", "http://localhost:7071/base"),
        ("VERIFY_BASE_URL", "http://localhost:invalid"),
    ],
)
def test_invalid_cloud_urls_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        EdgeConfig.from_environment()
