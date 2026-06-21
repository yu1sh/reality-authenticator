import pytest

from reality_cloud.config import CloudConfig


def test_azure_storage_requires_connection_or_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_AZURE_STORAGE", "true")
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)

    with pytest.raises(ValueError, match="Azure storage requires"):
        CloudConfig.from_environment()


def test_azure_storage_environment_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_AZURE_STORAGE", "true")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "storageaccount")
    monkeypatch.setenv("AZURE_STORAGE_SAS_TTL_SECONDS", "600")

    config = CloudConfig.from_environment()

    assert config.use_azure_storage is True
    assert config.azure_storage_account_name == "storageaccount"
    assert config.azure_storage_sas_ttl_seconds == 600


def test_key_vault_requires_url_and_key_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_AZURE_KEY_VAULT", "true")
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    monkeypatch.delenv("AZURE_KEY_VAULT_KEY_NAME", raising=False)

    with pytest.raises(ValueError, match="Azure Key Vault requires"):
        CloudConfig.from_environment()


def test_partial_service_principal_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)

    with pytest.raises(ValueError, match="must be configured together"):
        CloudConfig.from_environment()


def test_key_vault_environment_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_AZURE_KEY_VAULT", "true")
    monkeypatch.setenv(
        "AZURE_KEY_VAULT_URL", "https://reality.vault.azure.net"
    )
    monkeypatch.setenv("AZURE_KEY_VAULT_KEY_NAME", "reality-proof-signing")
    monkeypatch.setenv("AZURE_KEY_VAULT_KEY_VERSION", "version-1")

    config = CloudConfig.from_environment()

    assert config.use_azure_key_vault is True
    assert config.azure_key_vault_key_version == "version-1"
