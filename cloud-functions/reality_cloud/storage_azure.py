"""Azure Table and Blob implementation of the storage contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Mapping

from reality_core import canonical_json_bytes

from .blob_verification import BlobVerificationError, verify_manifest_blobs
from .storage_contract import (
    EvidenceVerification,
    StorageConflict,
    StorageCorrupt,
    StorageUnavailable,
    StoredRecord,
)

SasFactory = Callable[[str, str, str], str]


def _etag(entity: Mapping[str, object]) -> str:
    metadata = entity.get("metadata")
    if isinstance(metadata, Mapping) and isinstance(metadata.get("etag"), str):
        return str(metadata["etag"])
    value = entity.get("etag") or entity.get("odata.etag")
    return str(value or "")


def _decode_entity(entity: Mapping[str, object]) -> dict[str, object]:
    try:
        value = json.loads(str(entity["canonical_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise StorageCorrupt("stored Table entity is invalid") from error
    if not isinstance(value, dict):
        raise StorageCorrupt("stored Table entity is not an object")
    return value


def _is_named(error: Exception, *names: str) -> bool:
    return error.__class__.__name__ in names


class AzureStorageRepository:
    def __init__(
        self,
        *,
        sessions_table: object,
        evidence_table: object,
        proofs_table: object,
        evidence_container: object,
        proofs_container: object,
        sas_factory: SasFactory,
        devices_table: object | None = None,
        audit_logs_table: object | None = None,
    ) -> None:
        self.sessions_table = sessions_table
        self.evidence_table = evidence_table
        self.proofs_table = proofs_table
        self.devices_table = devices_table or sessions_table
        self.audit_logs_table = audit_logs_table or evidence_table
        self.evidence_container = evidence_container
        self.proofs_container = proofs_container
        self.sas_factory = sas_factory

    @staticmethod
    def _session_entity(session: Mapping[str, object]) -> dict[str, object]:
        entity: dict[str, object] = {
            "PartitionKey": "SESSION",
            "RowKey": str(session["session_id"]),
            "canonical_json": canonical_json_bytes(dict(session)).decode("utf-8"),
            "session_id": str(session["session_id"]),
            "status": str(session.get("status", "")),
            "device_id": str(session.get("device_id", "")),
            "proof_id": str(session.get("proof_id", "")),
            "failure_code": str(session.get("failure_code") or ""),
        }
        for name in (
            "challenge_nonce",
            "challenge_text",
            "voice_code",
            "created_at",
            "expires_at",
        ):
            value = session.get(name)
            if value is not None:
                entity[name] = str(value)
        button_count = session.get("button_count")
        if isinstance(button_count, int) and not isinstance(button_count, bool):
            entity["button_count"] = button_count
        return entity

    def create_session(self, session: Mapping[str, object]) -> StoredRecord:
        try:
            entity = self.sessions_table.create_entity(self._session_entity(session))
        except Exception as error:
            if _is_named(error, "ResourceExistsError", "HttpResponseError") and getattr(
                error, "status_code", 409
            ) == 409:
                raise StorageConflict("session already exists") from error
            raise StorageUnavailable("could not create Session") from error
        return StoredRecord(dict(session), f"SESSION|{_etag(entity)}")

    def save_session(self, session: Mapping[str, object]) -> None:
        current = self.load_session_record(str(session["session_id"]))
        if current is None:
            self.create_session(session)
        else:
            self.replace_session(session, current.etag)

    def load_session_record(self, session_id: str) -> StoredRecord | None:
        for partition in ("SESSION", "session"):
            try:
                entity = self.sessions_table.get_entity(partition, session_id)
            except Exception as error:
                if _is_named(error, "ResourceNotFoundError", "KeyError"):
                    continue
                raise StorageUnavailable("could not load Session") from error
            return StoredRecord(
                _decode_entity(entity),
                f"{partition}|{_etag(entity)}",
            )
        return None

    def load_session(self, session_id: str) -> dict[str, object] | None:
        record = self.load_session_record(session_id)
        return None if record is None else record.value

    def replace_session(
        self, session: Mapping[str, object], expected_etag: str
    ) -> StoredRecord:
        if "|" in expected_etag:
            partition, raw_etag = expected_etag.split("|", 1)
        else:
            partition, raw_etag = "SESSION", expected_etag
        entity = self._session_entity(session)
        entity["PartitionKey"] = partition
        try:
            try:
                from azure.core import MatchConditions
                from azure.data.tables import UpdateMode

                result = self.sessions_table.update_entity(
                    entity,
                    mode=UpdateMode.REPLACE,
                    etag=raw_etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            except ImportError:
                result = self.sessions_table.update_entity(
                    entity,
                    mode="replace",
                    etag=raw_etag,
                    match_condition="IfNotModified",
                )
        except Exception as error:
            if _is_named(error, "ResourceModifiedError", "HttpResponseError") and getattr(
                error, "status_code", 412
            ) in {409, 412}:
                raise StorageConflict("session changed") from error
            raise StorageUnavailable("could not replace Session") from error
        return StoredRecord(dict(session), f"{partition}|{_etag(result)}")

    @staticmethod
    def _upload_canonical(container: object, path: str, value: Mapping[str, object]) -> None:
        payload = canonical_json_bytes(dict(value))
        blob = container.get_blob_client(path)
        try:
            try:
                from azure.storage.blob import ContentSettings

                content_settings: object = ContentSettings(
                    content_type="application/json"
                )
            except ImportError:
                content_settings = {"content_type": "application/json"}
            blob.upload_blob(
                payload, overwrite=False, content_settings=content_settings
            )
        except Exception as error:
            if not _is_named(error, "ResourceExistsError"):
                raise StorageUnavailable("could not save Blob") from error
            try:
                existing = blob.download_blob().readall()
            except Exception as read_error:
                raise StorageUnavailable("could not compare existing Blob") from read_error
            if existing != payload:
                raise StorageConflict("Blob already contains different data") from error

    @staticmethod
    def _load_json_blob(container: object, path: str) -> dict[str, object] | None:
        blob = container.get_blob_client(path)
        try:
            payload = blob.download_blob().readall()
        except Exception as error:
            if _is_named(error, "ResourceNotFoundError"):
                return None
            raise StorageUnavailable("could not load Blob") from error
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StorageCorrupt("stored Blob is invalid JSON") from error
        if not isinstance(value, dict):
            raise StorageCorrupt("stored Blob is not an object")
        return value

    def save_manifest(self, manifest: Mapping[str, object]) -> None:
        session_id = str(manifest["session_id"])
        self._upload_canonical(
            self.evidence_container,
            f"evidence/{session_id}/manifest.json",
            manifest,
        )

    def load_manifest(self, session_id: str) -> dict[str, object] | None:
        return self._load_json_blob(
            self.evidence_container, f"evidence/{session_id}/manifest.json"
        )

    def save_ingest_result(self, result: Mapping[str, object]) -> None:
        entity: dict[str, object] = {
            "PartitionKey": "EVIDENCE",
            "RowKey": str(result["session_id"]),
            "canonical_json": canonical_json_bytes(dict(result)).decode("utf-8"),
            "status": str(result.get("status", "")),
            "failure_code": str(result.get("failure_code") or ""),
            "manifest_hash": str(result.get("manifest_hash") or ""),
        }
        for name in (
            "verified_at",
            "image_blob_path",
            "image_sha256",
            "audio_blob_path",
            "audio_sha256",
        ):
            value = result.get(name)
            if value is not None:
                entity[name] = str(value)
        verified = result.get("evidence_bytes_verified")
        if isinstance(verified, bool):
            entity["evidence_bytes_verified"] = verified
        try:
            self.evidence_table.upsert_entity(entity, mode="replace")
        except Exception as error:
            raise StorageUnavailable("could not save ingest result") from error

    def save_proof(self, proof: Mapping[str, object]) -> None:
        proof_id = str(proof["proof_id"])
        path = f"proofs/{proof_id}.json"
        self._upload_canonical(self.proofs_container, path, proof)
        entity = {
            "PartitionKey": "PROOF",
            "RowKey": proof_id,
            "canonical_json": canonical_json_bytes(dict(proof)).decode("utf-8"),
            "proof_id": proof_id,
            "session_id": str(proof.get("session_id", "")),
            "device_id": str(proof.get("device_id", "")),
            "record_hash": str(proof.get("record_hash", "")),
            "manifest_hash": str(proof.get("manifest_hash", "")),
            "signature_algorithm": str(proof.get("signature_algorithm", "")),
            "key_id": str(proof.get("key_id", proof.get("signature_key_id", ""))),
            "signed_at": str(proof.get("signed_at", proof.get("created_at", ""))),
            "blob_path": path,
            "created_at": str(proof.get("created_at", "")),
        }
        try:
            self.proofs_table.upsert_entity(entity, mode="replace")
        except Exception as error:
            raise StorageUnavailable("could not save Proof index") from error

    def load_proof(self, proof_id: str) -> dict[str, object] | None:
        return self._load_json_blob(self.proofs_container, f"proofs/{proof_id}.json")

    def save_device(self, device: Mapping[str, object]) -> None:
        device_id = str(device["device_id"])
        partition = "DEVICE"
        try:
            self.devices_table.get_entity("DEVICE", device_id)
        except Exception as error:
            if not _is_named(error, "ResourceNotFoundError", "KeyError"):
                raise StorageUnavailable("could not load Device") from error
            try:
                self.devices_table.get_entity("device", device_id)
                partition = "device"
            except Exception as legacy_error:
                if not _is_named(
                    legacy_error, "ResourceNotFoundError", "KeyError"
                ):
                    raise StorageUnavailable(
                        "could not load Device"
                    ) from legacy_error
        entity = {
            "PartitionKey": partition,
            "RowKey": str(device["device_id"]),
            "canonical_json": canonical_json_bytes(dict(device)).decode("utf-8"),
            "device_id": device_id,
            "status": str(device.get("status", "")),
            "display_name": str(device.get("display_name", "")),
            "created_at": str(device.get("created_at", "")),
            "last_seen_at": str(device.get("last_seen_at") or ""),
            "iot_hub_device_id": str(device.get("iot_hub_device_id", "")),
            "public_note": str(device.get("public_note") or ""),
        }
        try:
            self.devices_table.upsert_entity(entity, mode="replace")
        except Exception as error:
            raise StorageUnavailable("could not save Device") from error

    def load_device(self, device_id: str) -> dict[str, object] | None:
        for partition in ("DEVICE", "device"):
            try:
                entity = self.devices_table.get_entity(partition, device_id)
            except Exception as error:
                if _is_named(error, "ResourceNotFoundError", "KeyError"):
                    continue
                raise StorageUnavailable("could not load Device") from error
            return _decode_entity(entity)
        return None

    def list_devices(self) -> list[dict[str, object]]:
        try:
            by_device_id: dict[str, dict[str, object]] = {}
            for partition in ("device", "DEVICE"):
                entities = self.devices_table.query_entities(
                    f"PartitionKey eq '{partition}'"
                )
                for entity in entities:
                    decoded = _decode_entity(entity)
                    device_id = decoded.get("device_id")
                    if isinstance(device_id, str) and device_id:
                        by_device_id[device_id] = decoded
            return [by_device_id[key] for key in sorted(by_device_id)]
        except Exception as error:
            raise StorageUnavailable("could not list Devices") from error

    def save_audit_log(self, event: Mapping[str, object]) -> None:
        created_at = str(event["created_at"])
        detail = event.get("detail")
        detail_json = canonical_json_bytes(
            dict(detail) if isinstance(detail, Mapping) else {}
        ).decode("utf-8")
        entity = {
            "PartitionKey": created_at[:10].replace("-", ""),
            "RowKey": str(event["event_id"]),
            "canonical_json": canonical_json_bytes(dict(event)).decode("utf-8"),
            "event_type": str(event.get("event_type", "")),
            "session_id": str(event.get("session_id") or ""),
            "proof_id": str(event.get("proof_id") or ""),
            "device_id": str(event.get("device_id") or ""),
            "created_at": created_at,
            "message": str(event.get("message") or ""),
            "detail": detail_json,
        }
        try:
            self.audit_logs_table.create_entity(entity)
        except Exception as error:
            if _is_named(error, "ResourceExistsError"):
                return
            raise StorageUnavailable("could not save AuditLog") from error

    def save_qr(self, proof_id: str, png: bytes) -> None:
        blob = self.proofs_container.get_blob_client(f"proofs/{proof_id}.png")
        try:
            try:
                from azure.storage.blob import ContentSettings

                content_settings: object = ContentSettings(
                    content_type="image/png"
                )
            except ImportError:
                content_settings = {"content_type": "image/png"}
            blob.upload_blob(
                png,
                overwrite=True,
                content_settings=content_settings,
            )
        except Exception as error:
            raise StorageUnavailable("could not save Proof QR") from error

    def load_qr(self, proof_id: str) -> bytes | None:
        blob = self.proofs_container.get_blob_client(f"proofs/{proof_id}.png")
        try:
            return bytes(blob.download_blob().readall())
        except Exception as error:
            if _is_named(error, "ResourceNotFoundError"):
                return None
            raise StorageUnavailable("could not load Proof QR") from error

    def create_upload_targets(
        self, session_id: str, expires_at: str
    ) -> dict[str, object]:
        targets: dict[str, object] = {
            "mode": "sas_url",
            "expires_at": expires_at,
        }
        try:
            for name, extension, content_type in (
                ("image", "jpg", "image/jpeg"),
                ("audio", "wav", "audio/wav"),
            ):
                path = f"evidence/{session_id}/{name}.{extension}"
                targets[name] = {
                    "blob_path": path,
                    "url": self.sas_factory(path, content_type, expires_at),
                    "content_type": content_type,
                }
        except Exception as error:
            raise StorageUnavailable(
                "could not create evidence upload targets"
            ) from error
        return targets

    def verify_evidence_files(
        self, manifest: Mapping[str, object]
    ) -> EvidenceVerification:
        try:
            verify_manifest_blobs(self.evidence_container, manifest)
        except BlobVerificationError:
            raise
        except Exception as error:
            raise StorageUnavailable("could not verify evidence blobs") from error
        return EvidenceVerification(
            verified=True,
            verified_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            image_hash=True,
            audio_hash=True,
        )
