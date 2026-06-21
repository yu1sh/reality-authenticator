from dataclasses import dataclass, field

import pytest

from reality_cloud.signing_contract import SigningUnavailable
from reality_cloud.signing_key_vault import (
    AzureKeyVaultSigner,
    AzureKeyVaultVerifier,
    PS256,
)

KEY_ID = (
    "https://reality-test.vault.azure.net/keys/"
    "reality-proof-signing/version-1"
)


@dataclass
class Properties:
    enabled: bool = True


@dataclass
class Jwk:
    kty: str = "RSA"
    n: bytes = b"x" * 384
    key_ops: tuple[str, ...] = ("sign", "verify")


@dataclass
class Key:
    id: str
    properties: Properties = field(default_factory=Properties)
    key: Jwk = field(default_factory=Jwk)


class KeyClient:
    vault_url = "https://reality-test.vault.azure.net"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def get_key(self, name: str, version: str | None):
        self.calls.append((name, version))
        return Key(KEY_ID)


class SignResult:
    signature = b"ps256-signature"


class VerifyResult:
    def __init__(self, valid: bool) -> None:
        self.is_valid = valid


class CryptoClient:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.sign_calls = []
        self.verify_calls = []

    def sign(self, algorithm: str, digest: bytes):
        self.sign_calls.append((algorithm, digest))
        return SignResult()

    def verify(
        self, algorithm: str, digest: bytes, signature: bytes
    ) -> VerifyResult:
        self.verify_calls.append((algorithm, digest, signature))
        return VerifyResult(self.valid)


def test_key_vault_signer_resolves_version_and_signs_digest() -> None:
    key_client = KeyClient()
    crypto = CryptoClient()
    signer = AzureKeyVaultSigner(
        key_client=key_client,
        key_name="reality-proof-signing",
        key_version="version-1",
        crypto_client_factory=lambda key_id: crypto,
    )

    profile = signer.resolve_profile()
    signature = signer.sign_digest(b"x" * 32, profile.key_id)

    assert profile.algorithm == PS256
    assert profile.key_id == KEY_ID
    assert key_client.calls == [("reality-proof-signing", "version-1")]
    assert crypto.sign_calls == [(PS256, b"x" * 32)]
    assert signature == b"ps256-signature"


def test_key_vault_signer_allows_latest_version_resolution() -> None:
    key_client = KeyClient()
    signer = AzureKeyVaultSigner(
        key_client=key_client,
        key_name="reality-proof-signing",
        key_version=None,
        crypto_client_factory=lambda key_id: CryptoClient(),
    )

    signer.resolve_profile()

    assert key_client.calls == [("reality-proof-signing", None)]


def test_key_vault_verifier_uses_versioned_key_id() -> None:
    crypto = CryptoClient()
    verifier = AzureKeyVaultVerifier(
        lambda key_id: crypto,
        vault_url="https://reality-test.vault.azure.net",
        key_name="reality-proof-signing",
    )

    assert verifier.verify_digest(b"x" * 32, b"signature", PS256, KEY_ID)
    assert crypto.verify_calls == [(PS256, b"x" * 32, b"signature")]


@pytest.mark.parametrize(
    "key_id",
    [
        "http://reality-test.vault.azure.net/keys/reality-proof-signing/v1",
        "https://other.vault.azure.net/keys/reality-proof-signing/v1",
        "https://reality-test.vault.azure.net/keys/other/v1",
        "https://reality-test.vault.azure.net/keys/reality-proof-signing",
    ],
)
def test_key_vault_verifier_rejects_untrusted_key_id(key_id: str) -> None:
    verifier = AzureKeyVaultVerifier(
        lambda value: CryptoClient(),
        vault_url="https://reality-test.vault.azure.net",
        key_name="reality-proof-signing",
    )

    assert not verifier.verify_digest(b"x" * 32, b"signature", PS256, key_id)


def test_key_vault_errors_do_not_leak_sdk_details() -> None:
    class FailingKeyClient(KeyClient):
        def get_key(self, name: str, version: str | None):
            raise RuntimeError("token=secret")

    signer = AzureKeyVaultSigner(
        key_client=FailingKeyClient(),
        key_name="reality-proof-signing",
        key_version=None,
        crypto_client_factory=lambda key_id: CryptoClient(),
    )

    with pytest.raises(SigningUnavailable) as caught:
        signer.resolve_profile()
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "key",
    [
        Key(KEY_ID, key=Jwk(kty="EC")),
        Key(KEY_ID, key=Jwk(n=b"x" * 256)),
        Key(KEY_ID, key=Jwk(key_ops=("verify",))),
        Key(KEY_ID, properties=Properties(enabled=False)),
    ],
)
def test_key_vault_signer_rejects_incompatible_keys(key: Key) -> None:
    class IncompatibleKeyClient(KeyClient):
        def get_key(self, name: str, version: str | None):
            return key

    signer = AzureKeyVaultSigner(
        key_client=IncompatibleKeyClient(),
        key_name="reality-proof-signing",
        key_version=None,
        crypto_client_factory=lambda key_id: CryptoClient(),
    )

    with pytest.raises(SigningUnavailable, match="RSA 3072"):
        signer.resolve_profile()
