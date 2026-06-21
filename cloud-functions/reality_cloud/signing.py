"""Local signing stub used before Azure Key Vault integration."""

from __future__ import annotations

import base64
import hashlib
import hmac

from .signing_contract import Signer, SigningProfile, Verifier

SIGNATURE_ALGORITHM = "STUB-HS256"


def _secret_bytes(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret:
        raise ValueError("stub signing secret is required")
    return secret.encode("utf-8")


def sign_record_hash(record_hash: str, secret: str) -> str:
    """Sign a lowercase SHA-256 hex digest with the local HMAC stub."""

    try:
        digest_bytes = bytes.fromhex(record_hash)
    except ValueError as error:
        raise ValueError("record_hash must be hexadecimal") from error
    if len(digest_bytes) != hashlib.sha256().digest_size:
        raise ValueError("record_hash must be a SHA-256 digest")

    signature = hmac.new(_secret_bytes(secret), digest_bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def verify_record_signature(record_hash: str, signature: object, secret: str) -> bool:
    """Verify a local HMAC stub signature without timing-sensitive comparison."""

    if not isinstance(signature, str):
        return False
    try:
        expected = sign_record_hash(record_hash, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, signature)


class LocalStubSigner(Signer):
    def __init__(self, secret: str, key_id: str = "local-stub-v1") -> None:
        _secret_bytes(secret)
        if not key_id:
            raise ValueError("stub signing key ID is required")
        self.secret = secret
        self.key_id = key_id

    def resolve_profile(self) -> SigningProfile:
        return SigningProfile(SIGNATURE_ALGORITHM, self.key_id)

    def sign_digest(self, digest: bytes, key_id: str) -> bytes:
        if key_id != self.key_id or len(digest) != hashlib.sha256().digest_size:
            raise ValueError("invalid stub signing input")
        return hmac.new(
            _secret_bytes(self.secret), digest, hashlib.sha256
        ).digest()


class LocalStubVerifier(Verifier):
    def __init__(self, secret: str, key_id: str = "local-stub-v1") -> None:
        _secret_bytes(secret)
        self.secret = secret
        self.key_id = key_id

    def verify_digest(
        self,
        digest: bytes,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool:
        if (
            algorithm != SIGNATURE_ALGORITHM
            or key_id != self.key_id
            or len(digest) != hashlib.sha256().digest_size
        ):
            return False
        expected = hmac.new(
            _secret_bytes(self.secret), digest, hashlib.sha256
        ).digest()
        return hmac.compare_digest(expected, signature)


def create_signer(config: object) -> Signer:
    if getattr(config, "use_azure_key_vault", False):
        from .signing_key_vault import create_key_vault_clients

        signer, _ = create_key_vault_clients(
            vault_url=str(getattr(config, "azure_key_vault_url")),
            key_name=str(getattr(config, "azure_key_vault_key_name")),
            key_version=getattr(config, "azure_key_vault_key_version"),
            tenant_id=getattr(config, "azure_tenant_id"),
            client_id=getattr(config, "azure_client_id"),
            client_secret=getattr(config, "azure_client_secret"),
        )
        return signer
    secret = getattr(config, "stub_signing_secret", None)
    if not secret:
        raise ValueError("stub signing configuration is incomplete")
    return LocalStubSigner(secret, str(getattr(config, "signature_key_id")))


def create_verifier(config: object) -> Verifier | None:
    if getattr(config, "use_azure_key_vault", False):
        from .signing_key_vault import create_key_vault_clients

        _, verifier = create_key_vault_clients(
            vault_url=str(getattr(config, "azure_key_vault_url")),
            key_name=str(getattr(config, "azure_key_vault_key_name")),
            key_version=getattr(config, "azure_key_vault_key_version"),
            tenant_id=getattr(config, "azure_tenant_id"),
            client_id=getattr(config, "azure_client_id"),
            client_secret=getattr(config, "azure_client_secret"),
        )
        return verifier
    return None
