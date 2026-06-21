import json
from datetime import datetime, timezone

from reality_cloud.storage_azure import AzureStorageRepository
from reality_cloud.storage_contract import StorageUnavailable


class Table:
    def __init__(self) -> None:
        self.entities: dict[tuple[str, str], dict[str, object]] = {}
        self.version = 0

    def _stored(self, entity):
        self.version += 1
        value = dict(entity)
        value["etag"] = f"etag-{self.version}"
        self.entities[(str(value["PartitionKey"]), str(value["RowKey"]))] = value
        return value

    def create_entity(self, entity):
        return self._stored(entity)

    def get_entity(self, partition_key, row_key):
        return self.entities[(partition_key, row_key)]

    def update_entity(self, entity, **kwargs):
        assert kwargs["etag"].startswith("etag-")
        return self._stored(entity)

    def upsert_entity(self, entity, **kwargs):
        return self._stored(entity)

    def query_entities(self, filter_text):
        partition = filter_text.split("'")[1]
        return [
            entity
            for (partition_key, _), entity in self.entities.items()
            if partition_key == partition
        ]


class Download:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def readall(self) -> bytes:
        return self.data


class Blob:
    def __init__(self, url: str) -> None:
        self.url = url
        self.data: bytes | None = None

    def upload_blob(self, data, **kwargs):
        self.data = bytes(data)

    def download_blob(self):
        return Download(self.data or b"")


class Container:
    def __init__(self) -> None:
        self.blobs: dict[str, Blob] = {}

    def get_blob_client(self, path: str):
        return self.blobs.setdefault(path, Blob(f"https://storage/{path}"))


def repository() -> AzureStorageRepository:
    return AzureStorageRepository(
        sessions_table=Table(),
        evidence_table=Table(),
        proofs_table=Table(),
        evidence_container=Container(),
        proofs_container=Container(),
        sas_factory=lambda path, content_type, expires: f"https://storage/{path}?sig",
    )


def test_azure_repository_round_trip_and_index() -> None:
    storage = repository()
    session = {
        "session_id": "session-1",
        "device_id": "device-1",
        "status": "challenge_issued",
        "challenge_nonce": "nonce-1",
        "challenge_text": "challenge",
        "button_count": 2,
        "voice_code": "0007",
        "created_at": "2026-06-15T00:00:00.000+00:00",
        "expires_at": "2026-06-15T00:00:45.000+00:00",
    }
    created = storage.create_session(session)
    changed = dict(session, status="evidence_uploaded")
    storage.replace_session(changed, created.etag)
    manifest = {"session_id": "session-1", "schema_version": "1.0"}
    proof = {
        "proof_id": "RP-proof-1",
        "session_id": "session-1",
        "device_id": "device-1",
    }

    storage.save_manifest(manifest)
    storage.save_ingest_result(
        {
            "session_id": "session-1",
            "status": "evidence_uploaded",
            "manifest_hash": "a" * 64,
            "evidence_bytes_verified": True,
            "verified_at": "2026-06-15T00:00:10.000+00:00",
            "image_blob_path": "evidence/session-1/image.jpg",
            "image_sha256": "b" * 64,
            "audio_blob_path": "evidence/session-1/audio.wav",
            "audio_sha256": "c" * 64,
        }
    )
    storage.save_proof(proof)

    assert storage.load_session("session-1") == changed
    assert storage.load_manifest("session-1") == manifest
    assert storage.load_proof("RP-proof-1") == proof
    session_entity = storage.sessions_table.entities[("SESSION", "session-1")]
    assert session_entity["session_id"] == "session-1"
    assert session_entity["challenge_nonce"] == "nonce-1"
    assert session_entity["button_count"] == 2
    evidence_entity = storage.evidence_table.entities[("EVIDENCE", "session-1")]
    assert evidence_entity["evidence_bytes_verified"] is True
    assert evidence_entity["image_sha256"] == "b" * 64
    proof_entity = storage.proofs_table.entities[("PROOF", "RP-proof-1")]
    assert proof_entity["proof_id"] == "RP-proof-1"


def test_azure_upload_targets_are_scoped() -> None:
    storage = repository()
    targets = storage.create_upload_targets(
        "session-1",
        datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
    )

    assert targets["mode"] == "sas_url"
    assert targets["image"]["blob_path"] == "evidence/session-1/image.jpg"
    assert targets["audio"]["blob_path"] == "evidence/session-1/audio.wav"
    assert targets["audio"]["content_type"] == "audio/wav"
    assert targets["image"]["url"].endswith("?sig")


def test_upload_target_failure_is_normalized() -> None:
    storage = repository()
    storage.sas_factory = lambda *args: (_ for _ in ()).throw(
        RuntimeError("credential detail")
    )

    try:
        storage.create_upload_targets(
            "session-1",
            datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
        )
    except StorageUnavailable as error:
        assert "credential detail" not in str(error)
    else:
        raise AssertionError("StorageUnavailable was not raised")


def test_device_schema_and_legacy_partition_updates_are_compatible() -> None:
    storage = repository()
    legacy = {
        "device_id": "device-1",
        "display_name": "Old name",
        "status": "active",
        "created_at": "2026-06-01T00:00:00.000+00:00",
        "last_seen_at": None,
        "iot_hub_device_id": "device-1",
        "public_note": "",
    }
    storage.devices_table._stored(
        {
            "PartitionKey": "device",
            "RowKey": "device-1",
            "canonical_json": json.dumps(legacy),
        }
    )
    updated = dict(
        legacy,
        display_name="Anchor",
        last_seen_at="2026-06-15T00:00:00.000+00:00",
    )

    storage.save_device(updated)

    assert ("DEVICE", "device-1") not in storage.devices_table.entities
    entity = storage.devices_table.entities[("device", "device-1")]
    assert entity["device_id"] == "device-1"
    assert entity["display_name"] == "Anchor"
    assert entity["iot_hub_device_id"] == "device-1"
    assert storage.list_devices() == [updated]


def test_audit_table_persists_message_and_structured_detail() -> None:
    storage = repository()
    event = {
        "event_id": "event-1",
        "event_type": "error",
        "session_id": "session-1",
        "proof_id": None,
        "device_id": "device-1",
        "created_at": "2026-06-15T00:00:00.000+00:00",
        "message": "Signing failed",
        "detail": {"failure_code": "ERR_SIGNATURE_FAILED"},
    }

    storage.save_audit_log(event)

    entity = storage.audit_logs_table.entities[("20260615", "event-1")]
    assert entity["message"] == "Signing failed"
    assert json.loads(entity["detail"]) == {
        "failure_code": "ERR_SIGNATURE_FAILED"
    }
