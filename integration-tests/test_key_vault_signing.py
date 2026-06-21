from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(
    os.getenv("RUN_AZURE_KEY_VAULT_INTEGRATION") != "1",
    reason="real Azure Key Vault integration is opt-in",
)
def test_real_key_vault_sign_and_verify() -> None:
    from reality_cloud.signing_key_vault import create_key_vault_clients

    signer, verifier = create_key_vault_clients(
        vault_url=os.environ["AZURE_KEY_VAULT_URL"],
        key_name=os.environ["AZURE_KEY_VAULT_KEY_NAME"],
        key_version=os.getenv("AZURE_KEY_VAULT_KEY_VERSION") or None,
        tenant_id=os.getenv("AZURE_TENANT_ID") or None,
        client_id=os.getenv("AZURE_CLIENT_ID") or None,
        client_secret=os.getenv("AZURE_CLIENT_SECRET") or None,
    )
    profile = signer.resolve_profile()
    digest = b"x" * 32
    signature = signer.sign_digest(digest, profile.key_id)

    assert verifier.verify_digest(
        digest, signature, profile.algorithm, profile.key_id
    )
