"""Azure Key Vault PS256 signing and verification."""

from __future__ import annotations

import base64
from collections.abc import Callable
from urllib.parse import urlsplit

from .signing_contract import (
    Signer,
    SigningProfile,
    SigningUnavailable,
    Verifier,
)

PS256 = "PS256"


def _validate_versioned_key_id(
    key_id: str, *, vault_url: str | None = None, key_name: str | None = None
) -> bool:
    try:
        parsed = urlsplit(key_id)
        parts = [part for part in parsed.path.split("/") if part]
        expected = urlsplit(vault_url) if vault_url else None
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and len(parts) == 3
        and parts[0] == "keys"
        and bool(parts[1])
        and bool(parts[2])
        and (key_name is None or parts[1] == key_name)
        and (
            expected is None
            or (parsed.scheme, parsed.hostname, parsed.port)
            == (expected.scheme, expected.hostname, expected.port)
        )
        and not parsed.query
        and not parsed.fragment
    )


class AzureKeyVaultSigner(Signer):
    def __init__(
        self,
        *,
        key_client: object,
        key_name: str,
        key_version: str | None,
        crypto_client_factory: Callable[[str], object],
    ) -> None:
        self.key_client = key_client
        self.key_name = key_name
        self.key_version = key_version
        self.crypto_client_factory = crypto_client_factory
        self.vault_url = str(getattr(key_client, "vault_url", "")) or None

    def resolve_profile(self) -> SigningProfile:
        try:
            key = self.key_client.get_key(self.key_name, self.key_version)
            key_id = str(key.id)
        except Exception as error:
            raise SigningUnavailable("Key Vault signing key is unavailable") from error
        properties = getattr(key, "properties", None)
        jwk = getattr(key, "key", None)
        key_type = str(getattr(jwk, "kty", "")).upper()
        modulus = getattr(jwk, "n", None)
        key_ops = {str(value).lower() for value in (getattr(jwk, "key_ops", None) or [])}
        if (
            properties is None
            or getattr(properties, "enabled", None) is not True
            or key_type not in {"RSA", "KEYTYPE.RSA"}
            or not isinstance(modulus, bytes)
            or len(modulus) * 8 < 3072
            or not {"sign", "verify"} <= key_ops
        ):
            raise SigningUnavailable(
                "Key Vault signing key must be enabled RSA 3072 with sign/verify"
            )
        if not _validate_versioned_key_id(
            key_id, vault_url=self.vault_url, key_name=self.key_name
        ):
            raise SigningUnavailable("Key Vault returned an invalid key ID")
        exponent = getattr(jwk, "e", None) or b"\x01\x00\x01"
        if not isinstance(exponent, bytes):
            raise SigningUnavailable("Key Vault returned invalid RSA metadata")

        def encode(value: bytes) -> str:
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

        return SigningProfile(
            PS256,
            key_id,
            {
                "kty": "RSA",
                "n": encode(modulus),
                "e": encode(exponent),
                "bits": len(modulus) * 8,
            },
        )

    def sign_digest(self, digest: bytes, key_id: str) -> bytes:
        if len(digest) != 32:
            raise ValueError("PS256 requires a SHA-256 digest")
        try:
            client = self.crypto_client_factory(key_id)
            result = client.sign(PS256, digest)
            signature = bytes(result.signature)
        except Exception as error:
            raise SigningUnavailable("Key Vault signing failed") from error
        if not signature:
            raise SigningUnavailable("Key Vault returned an empty signature")
        return signature


class AzureKeyVaultVerifier(Verifier):
    def __init__(
        self,
        crypto_client_factory: Callable[[str], object],
        *,
        vault_url: str | None = None,
        key_name: str | None = None,
    ) -> None:
        self.crypto_client_factory = crypto_client_factory
        self.vault_url = vault_url
        self.key_name = key_name

    def verify_digest(
        self,
        digest: bytes,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool:
        if (
            algorithm != PS256
            or len(digest) != 32
            or not _validate_versioned_key_id(
                key_id, vault_url=self.vault_url, key_name=self.key_name
            )
        ):
            return False
        try:
            result = self.crypto_client_factory(key_id).verify(
                PS256, digest, signature
            )
        except Exception as error:
            raise SigningUnavailable("Key Vault verification failed") from error
        return result.is_valid is True


def create_key_vault_clients(
    *,
    vault_url: str,
    key_name: str,
    key_version: str | None,
    tenant_id: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[AzureKeyVaultSigner, AzureKeyVaultVerifier]:
    try:
        from azure.identity import ClientSecretCredential, DefaultAzureCredential
        from azure.keyvault.keys import KeyClient
        from azure.keyvault.keys.crypto import CryptographyClient, SignatureAlgorithm
    except ImportError as error:
        raise SigningUnavailable("Azure Key Vault dependencies are not installed") from error

    if tenant_id and client_id and client_secret:
        credential = ClientSecretCredential(tenant_id, client_id, client_secret)
    else:
        credential = DefaultAzureCredential()
    key_client = KeyClient(vault_url=vault_url, credential=credential)

    class CryptoClientAdapter:
        def __init__(self, key_id: str) -> None:
            self.client = CryptographyClient(key_id, credential=credential)

        def sign(self, algorithm: str, digest: bytes) -> object:
            if algorithm != PS256:
                raise ValueError("unsupported Key Vault signature algorithm")
            return self.client.sign(SignatureAlgorithm.ps256, digest)

        def verify(
            self, algorithm: str, digest: bytes, signature: bytes
        ) -> object:
            if algorithm != PS256:
                raise ValueError("unsupported Key Vault signature algorithm")
            return self.client.verify(
                SignatureAlgorithm.ps256, digest, signature
            )

    def crypto_client_factory(key_id: str) -> object:
        return CryptoClientAdapter(key_id)

    return (
        AzureKeyVaultSigner(
            key_client=key_client,
            key_name=key_name,
            key_version=key_version,
            crypto_client_factory=crypto_client_factory,
        ),
        AzureKeyVaultVerifier(
            crypto_client_factory, vault_url=vault_url, key_name=key_name
        ),
    )
