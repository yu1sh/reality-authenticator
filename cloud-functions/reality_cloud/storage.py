"""Local canonical JSON repository."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Mapping

from reality_core import canonical_json_bytes, sha256_bytes

from .storage_contract import EvidenceVerification, StorageConflict, StoredRecord

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class LocalJsonRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_identifier(value: str) -> None:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("identifier contains unsupported characters")

    def _session_path(self, session_id: str) -> Path:
        self._validate_identifier(session_id)
        return self.root / "sessions" / f"{session_id}.json"

    def _manifest_path(self, session_id: str) -> Path:
        self._validate_identifier(session_id)
        return self.root / "evidence" / session_id / "manifest.json"

    def _proof_path(self, proof_id: str) -> Path:
        self._validate_identifier(proof_id)
        return self.root / "proofs" / f"{proof_id}.json"

    def _device_path(self, device_id: str) -> Path:
        self._validate_identifier(device_id)
        return self.root / "devices" / f"{device_id}.json"

    def _qr_path(self, proof_id: str) -> Path:
        self._validate_identifier(proof_id)
        return self.root / "proofs" / f"{proof_id}.png"

    @staticmethod
    def _atomic_write(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json_bytes(dict(value))
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                try:
                    Path(temporary_path).unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError(f"stored JSON at {path} is not an object")
        return value

    def save_session(self, session: Mapping[str, object]) -> None:
        self._atomic_write(
            self._session_path(str(session["session_id"])),
            session,
        )

    @staticmethod
    def _etag(value: Mapping[str, object]) -> str:
        return sha256_bytes(canonical_json_bytes(dict(value)))

    def create_session(self, session: Mapping[str, object]) -> StoredRecord:
        with self._lock:
            path = self._session_path(str(session["session_id"]))
            if path.exists():
                raise StorageConflict("session already exists")
            self._atomic_write(path, session)
            return StoredRecord(dict(session), self._etag(session))

    def load_session(self, session_id: str) -> dict[str, object] | None:
        return self._read(self._session_path(session_id))

    def load_session_record(self, session_id: str) -> StoredRecord | None:
        value = self.load_session(session_id)
        return None if value is None else StoredRecord(value, self._etag(value))

    def replace_session(
        self, session: Mapping[str, object], expected_etag: str
    ) -> StoredRecord:
        with self._lock:
            current = self.load_session_record(str(session["session_id"]))
            if current is None or current.etag != expected_etag:
                raise StorageConflict("session changed")
            self.save_session(session)
            return StoredRecord(dict(session), self._etag(session))

    def save_manifest(self, manifest: Mapping[str, object]) -> None:
        self._atomic_write(
            self._manifest_path(str(manifest["session_id"])),
            manifest,
        )

    def load_manifest(self, session_id: str) -> dict[str, object] | None:
        return self._read(self._manifest_path(session_id))

    def save_ingest_result(self, result: Mapping[str, object]) -> None:
        self._atomic_write(
            self.root
            / "evidence"
            / str(result["session_id"])
            / "ingest-result.json",
            result,
        )

    def save_proof(self, proof: Mapping[str, object]) -> None:
        self._atomic_write(
            self._proof_path(str(proof["proof_id"])),
            proof,
        )

    def load_proof(self, proof_id: str) -> dict[str, object] | None:
        return self._read(self._proof_path(proof_id))

    def save_device(self, device: Mapping[str, object]) -> None:
        self._atomic_write(
            self._device_path(str(device["device_id"])),
            device,
        )

    def load_device(self, device_id: str) -> dict[str, object] | None:
        return self._read(self._device_path(device_id))

    def list_devices(self) -> list[dict[str, object]]:
        directory = self.root / "devices"
        if not directory.exists():
            return []
        devices: list[dict[str, object]] = []
        for path in sorted(directory.glob("*.json")):
            value = self._read(path)
            if value is not None:
                devices.append(value)
        return devices

    def save_audit_log(self, event: Mapping[str, object]) -> None:
        date = str(event["created_at"])[:10].replace("-", "")
        self._atomic_write(
            self.root / "audit" / date / f"{event['event_id']}.json",
            event,
        )

    def save_qr(self, proof_id: str, png: bytes) -> None:
        path = self._qr_path(proof_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(png)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                try:
                    Path(temporary_path).unlink()
                except FileNotFoundError:
                    pass

    def load_qr(self, proof_id: str) -> bytes | None:
        try:
            return self._qr_path(proof_id).read_bytes()
        except FileNotFoundError:
            return None

    def create_upload_targets(
        self, session_id: str, expires_at: str
    ) -> dict[str, object] | None:
        return None

    def verify_evidence_files(
        self, manifest: Mapping[str, object]
    ) -> EvidenceVerification:
        return EvidenceVerification(verified=False)


def create_storage(config: object) -> object:
    if getattr(config, "use_azure_storage", False):
        from .azure_clients import create_azure_repository

        return create_azure_repository(config)
    return LocalJsonRepository(getattr(config, "local_data_dir"))
