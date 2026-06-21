"""Storage contracts shared by local and Azure implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class StorageError(RuntimeError):
    """Base error raised at the storage boundary."""


class StorageConflict(StorageError):
    """A conditional create or replace lost an optimistic concurrency race."""


class StorageUnavailable(StorageError):
    """The backing storage service could not be reached."""


class StorageCorrupt(StorageError):
    """Stored data could not be decoded or did not match its expected shape."""


@dataclass(frozen=True)
class StoredRecord:
    value: dict[str, object]
    etag: str


@dataclass(frozen=True)
class EvidenceVerification:
    verified: bool
    verified_at: str | None = None
    image_hash: bool | None = None
    audio_hash: bool | None = None


class RecordRepository(Protocol):
    def save_session(self, session: Mapping[str, object]) -> None: ...

    def load_session(self, session_id: str) -> dict[str, object] | None: ...

    def create_session(self, session: Mapping[str, object]) -> StoredRecord: ...

    def load_session_record(self, session_id: str) -> StoredRecord | None: ...

    def replace_session(
        self, session: Mapping[str, object], expected_etag: str
    ) -> StoredRecord: ...

    def save_manifest(self, manifest: Mapping[str, object]) -> None: ...

    def load_manifest(self, session_id: str) -> dict[str, object] | None: ...

    def save_ingest_result(self, result: Mapping[str, object]) -> None: ...

    def save_proof(self, proof: Mapping[str, object]) -> None: ...

    def load_proof(self, proof_id: str) -> dict[str, object] | None: ...

    def save_device(self, device: Mapping[str, object]) -> None: ...

    def load_device(self, device_id: str) -> dict[str, object] | None: ...

    def list_devices(self) -> list[dict[str, object]]: ...

    def save_audit_log(self, event: Mapping[str, object]) -> None: ...

    def save_qr(self, proof_id: str, png: bytes) -> None: ...

    def load_qr(self, proof_id: str) -> bytes | None: ...


class EvidenceObjectStore(Protocol):
    def create_upload_targets(
        self, session_id: str, expires_at: str
    ) -> dict[str, object] | None: ...

    def verify_evidence_files(
        self, manifest: Mapping[str, object]
    ) -> EvidenceVerification: ...


class StorageRepository(RecordRepository, EvidenceObjectStore, Protocol):
    pass
