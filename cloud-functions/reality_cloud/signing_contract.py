"""Signing contracts independent of Azure SDK types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class SigningError(RuntimeError):
    """Base error raised by signing infrastructure."""


class SigningUnavailable(SigningError):
    """The configured signing service could not complete an operation."""


@dataclass(frozen=True)
class SigningProfile:
    algorithm: str
    key_id: str
    public_key: Mapping[str, object] | None = None


class Signer(Protocol):
    def resolve_profile(self) -> SigningProfile: ...

    def sign_digest(self, digest: bytes, key_id: str) -> bytes: ...


class Verifier(Protocol):
    def verify_digest(
        self,
        digest: bytes,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool: ...
