from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
from pathlib import Path
from uuid import UUID

import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import start_session
from reality_cloud.iot import (
    AzureIotHubCommandDispatcher,
    TelemetryEnvelope,
    parse_telemetry,
)
from reality_cloud.storage import LocalJsonRepository
from reality_cloud.storage_contract import StorageUnavailable
from reality_cloud.telemetry import process_telemetry


class Dispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def send_start_session(
        self, device_id: str, command: dict[str, object]
    ) -> None:
        self.calls.append((device_id, dict(command)))


def test_start_session_dispatches_iot_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path,
        use_iot_hub=True,
        iot_hub_service_connection_string="HostName=fake",
    )
    repository = LocalJsonRepository(tmp_path)
    monkeypatch.setattr(
        repository,
        "create_upload_targets",
        lambda session_id, expires_at: {
            "mode": "sas_url",
            "expires_at": expires_at,
            "image": {
                "blob_path": f"evidence/{session_id}/image.jpg",
                "url": "https://storage/image?sig=secret",
                "content_type": "image/jpeg",
            },
            "audio": {
                "blob_path": f"evidence/{session_id}/audio.wav",
                "url": "https://storage/audio?sig=secret",
                "content_type": "audio/wav",
            },
        },
    )
    dispatcher = Dispatcher()
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    status, response = start_session(
        {"device_id": "raspi-anchor-01"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 15, tzinfo=timezone.utc),
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: 0,
        dispatcher=dispatcher,
    )

    assert status == 201
    assert repository.load_session(str(response["session_id"]))["status"] == (
        "waiting_device"
    )
    assert dispatcher.calls[0][0] == "raspi-anchor-01"
    assert dispatcher.calls[0][1]["message_type"] == "start_session"
    assert dispatcher.calls[0][1]["command_id"] == response["session_id"]
    assert dispatcher.calls[0][1]["upload"]["mode"] == "sas_url"
    assert "upload" not in response
    audit_events = [
        json.loads(path.read_text())
        for path in (repository.root / "audit").rglob("*.json")
    ]
    event_types = [event["event_type"] for event in audit_events]
    assert "session_created" in event_types
    assert "device_command_dispatched" in event_types
    assert {
        event["detail"].get("status")
        for event in audit_events
        if event["event_type"] == "session_status_updated"
    } >= {"challenge_issued", "waiting_device"}


def test_session_is_waiting_before_iot_command_is_sent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path,
        use_iot_hub=True,
        iot_hub_service_connection_string="HostName=fake",
    )
    repository = LocalJsonRepository(tmp_path)
    monkeypatch.setattr(
        repository,
        "create_upload_targets",
        lambda session_id, expires_at: {
            "mode": "sas_url",
            "expires_at": expires_at,
            "image": {"url": "https://storage/image?sig=secret"},
            "audio": {"url": "https://storage/audio?sig=secret"},
        },
    )

    class InspectingDispatcher:
        def send_start_session(self, device_id, command):
            saved = repository.load_session(str(command["session_id"]))
            assert saved["status"] == "waiting_device"

    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )
    start_session(
        {"device_id": "raspi-anchor-01"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 15, tzinfo=timezone.utc),
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: 0,
        dispatcher=InspectingDispatcher(),
    )


def test_telemetry_device_identity_is_taken_from_iot_metadata() -> None:
    envelope = parse_telemetry(
        b'{"message_type":"heartbeat","device_id":"spoofed"}',
        {"connection-device-id": "raspi-anchor-01"},
    )

    assert envelope.device_id == "raspi-anchor-01"


def test_iot_start_fails_closed_without_upload_targets(tmp_path: Path) -> None:
    config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path,
        use_iot_hub=True,
        iot_hub_service_connection_string="HostName=fake",
    )
    repository = LocalJsonRepository(tmp_path)
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    with pytest.raises(ApiError) as caught:
        start_session(
            {"device_id": "raspi-anchor-01"},
            config=config,
            repository=repository,
            clock=lambda: datetime(2026, 6, 15, tzinfo=timezone.utc),
            uuid_factory=lambda: next(uuids),
            randbelow=lambda limit: 0,
            dispatcher=Dispatcher(),
        )

    assert caught.value.code == "ERR_DEVICE_COMMAND"
    saved = repository.load_session(
        "11111111-1111-4111-8111-111111111111"
    )
    assert saved["status"] == "failed"


def test_iot_start_marks_session_failed_when_sas_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path,
        use_iot_hub=True,
        iot_hub_service_connection_string="HostName=fake",
    )
    repository = LocalJsonRepository(tmp_path)
    monkeypatch.setattr(
        repository,
        "create_upload_targets",
        lambda *args: (_ for _ in ()).throw(
            StorageUnavailable("SAS unavailable")
        ),
    )
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )

    with pytest.raises(ApiError) as caught:
        start_session(
            {"device_id": "raspi-anchor-01"},
            config=config,
            repository=repository,
            clock=lambda: datetime(2026, 6, 15, tzinfo=timezone.utc),
            uuid_factory=lambda: next(uuids),
            randbelow=lambda limit: 0,
            dispatcher=Dispatcher(),
        )

    assert caught.value.code == "ERR_STORAGE_UNAVAILABLE"
    saved = repository.load_session(
        "11111111-1111-4111-8111-111111111111"
    )
    assert saved["status"] == "failed"
    assert saved["failure_code"] == "ERR_STORAGE_UNAVAILABLE"


def test_iot_dispatcher_uses_scoped_rest_request() -> None:
    captured = {}

    class Response:
        def read(self):
            return b""

        def close(self):
            pass

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    dispatcher = AzureIotHubCommandDispatcher(
        host_name="test.azure-devices.net",
        policy_name="service-policy",
        policy_key=base64.b64encode(b"secret").decode("ascii"),
        opener=opener,
        clock=lambda: 1000,
    )
    dispatcher.send_start_session("device 1", {"message_type": "start_session"})

    request = captured["request"]
    assert "/devices/device%201/messages/deviceBound" in request.full_url
    assert request.get_header("Authorization").startswith(
        "SharedAccessSignature "
    )
    assert "secret" not in request.get_header("Authorization")


def test_manifest_telemetry_issues_proof(
    tmp_path: Path,
    config: CloudConfig,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    runtime_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=tmp_path,
        stub_signing_secret="test-signing-secret",
    )
    repository = LocalJsonRepository(tmp_path)
    session["status"] = "capturing"
    repository.save_session(session)

    result = process_telemetry(
        TelemetryEnvelope(
            "evidence_manifest",
            "raspi-anchor-01",
            {"message_type": "evidence_manifest", "manifest": manifest},
        ),
        config=runtime_config,
        repository=repository,
        clock=lambda: fixed_time,
    )

    saved = repository.load_session("session-1")
    assert result["issued"] is True
    assert saved["status"] == "proof_issued"
    assert repository.load_proof(str(saved["proof_id"])) is not None


def test_manifest_telemetry_records_capturing_when_status_arrives_late(
    tmp_path: Path,
    config: CloudConfig,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    runtime_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=tmp_path,
        stub_signing_secret="test-signing-secret",
    )
    repository = LocalJsonRepository(tmp_path)
    session["status"] = "waiting_device"
    repository.save_session(session)
    ticks = 0

    def clock() -> datetime:
        nonlocal ticks
        ticks += 1
        return fixed_time.replace(microsecond=ticks * 1000)

    process_telemetry(
        TelemetryEnvelope(
            "evidence_manifest",
            "raspi-anchor-01",
            {"message_type": "evidence_manifest", "manifest": manifest},
        ),
        config=runtime_config,
        repository=repository,
        clock=clock,
    )

    audit_events = [
        json.loads(path.read_text())
        for path in (repository.root / "audit").rglob("*.json")
    ]
    statuses = [
        event["detail"].get("status")
        for event in sorted(audit_events, key=lambda value: value["created_at"])
        if event["event_type"] == "session_status_updated"
    ]
    assert statuses[:4] == [
        "capturing",
        "evidence_uploaded",
        "validating",
        "verified",
    ]


def test_duplicate_manifest_telemetry_keeps_proof_issued(
    tmp_path: Path,
    config: CloudConfig,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    runtime_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=tmp_path,
        stub_signing_secret="test-signing-secret",
    )
    repository = LocalJsonRepository(tmp_path)
    session["status"] = "capturing"
    repository.save_session(session)
    envelope = TelemetryEnvelope(
        "evidence_manifest",
        "raspi-anchor-01",
        {"message_type": "evidence_manifest", "manifest": manifest},
    )

    first = process_telemetry(
        envelope,
        config=runtime_config,
        repository=repository,
        clock=lambda: fixed_time,
    )
    second = process_telemetry(
        envelope,
        config=runtime_config,
        repository=repository,
        clock=lambda: fixed_time,
    )

    saved = repository.load_session("session-1")
    assert saved["status"] == "proof_issued"
    assert second["proof_id"] == first["proof_id"]
    assert second["existing"] is True


def test_delayed_capturing_status_does_not_regress_session(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
) -> None:
    session["status"] = "proof_issued"
    session["proof_id"] = "RP-proof-1"
    repository.save_session(session)

    result = process_telemetry(
        TelemetryEnvelope(
            "device_status",
            "raspi-anchor-01",
            {
                "message_type": "device_status",
                "session_id": "session-1",
                "status": "capturing",
            },
        ),
        config=config,
        repository=repository,
    )

    assert result["accepted"] is True
    assert repository.load_session("session-1")["status"] == "proof_issued"


def test_unsupported_device_status_is_rejected(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
) -> None:
    repository.save_session(session)

    with pytest.raises(ApiError) as captured:
        process_telemetry(
            TelemetryEnvelope(
                "device_status",
                "raspi-anchor-01",
                {
                    "message_type": "device_status",
                    "session_id": "session-1",
                    "status": "unexpected",
                },
            ),
            config=config,
            repository=repository,
        )

    assert captured.value.code == "ERR_INVALID_TELEMETRY"


def test_manifest_telemetry_rejects_spoofed_device(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    repository.save_session(session)
    with pytest.raises(Exception) as caught:
        process_telemetry(
            TelemetryEnvelope(
                "evidence_manifest",
                "other-device",
                {"message_type": "evidence_manifest", "manifest": manifest},
            ),
            config=config,
            repository=repository,
        )
    assert getattr(caught.value, "code", None) in {
        "ERR_DEVICE_NOT_ALLOWED",
        "ERR_DEVICE_MISMATCH",
    }


def test_iot_trigger_records_processing_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path,
    )
    repository = LocalJsonRepository(tmp_path)

    class Event:
        iothub_metadata = {"connection-device-id": "raspi-anchor-01"}

        def get_body(self):
            return (
                b'{"message_type":"unsupported","session_id":"session-1"}'
            )

    monkeypatch.setattr(
        function_app,
        "_dependencies",
        lambda: (config, repository),
    )

    with pytest.raises(Exception):
        function_app.iot_evidence_telemetry(Event())

    audit_events = [
        json.loads(path.read_text())
        for path in (repository.root / "audit").rglob("*.json")
    ]
    error = next(
        event for event in audit_events if event["event_type"] == "error"
    )
    assert error["session_id"] == "session-1"
    assert error["device_id"] == "raspi-anchor-01"
    assert error["detail"]["failure_code"] == "ERR_INVALID_TELEMETRY"
