from pathlib import Path

import pytest

from reality_cloud.config import CloudConfig
from reality_cloud.signing import LocalStubSigner, create_signer
from reality_cloud.signing_contract import SigningProfile
from reality_cloud.signing_contract import SigningUnavailable


def config(**overrides) -> CloudConfig:
    values = {
        "allowed_device_ids": frozenset({"device-1"}),
        "local_data_dir": Path(".local-data"),
        "stub_signing_secret": "secret",
    }
    values.update(overrides)
    return CloudConfig(**values)


def test_factory_uses_local_stub_by_default() -> None:
    signer = create_signer(config())

    assert isinstance(signer, LocalStubSigner)
    assert signer.resolve_profile() == SigningProfile(
        "STUB-HS256", "local-stub-v1"
    )


def test_factory_does_not_fallback_when_key_vault_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**kwargs):
        raise SigningUnavailable("key vault failed")

    monkeypatch.setattr(
        "reality_cloud.signing_key_vault.create_key_vault_clients", fail
    )
    azure_config = config(
        use_azure_key_vault=True,
        azure_key_vault_url="https://vault.vault.azure.net",
        azure_key_vault_key_name="key",
    )

    with pytest.raises(SigningUnavailable, match="key vault failed"):
        create_signer(azure_config)
