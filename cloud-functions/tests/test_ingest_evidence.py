from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime

import azure.functions as func
import pytest

import function_app
from reality_cloud.errors import ApiError
from reality_cloud.handlers import ingest_evidence
from reality_cloud.storage import LocalJsonRepository


def test_valid_manifest_is_saved_and_session_is_updated(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    repository.save_session(session)

    status, response = ingest_evidence(
        manifest,
        repository=repository,
        clock=lambda: fixed_time,
    )

    assert status == 200
    assert response["status"] == "evidence_uploaded"
    assert repository.load_manifest("session-1") == manifest
    assert repository.load_session("session-1")["status"] == "evidence_uploaded"
    audit_events = [
        json.loads(path.read_text())
        for path in (repository.root / "audit").rglob("*.json")
    ]
    statuses = {
        event["detail"].get("status")
        for event in audit_events
        if event["event_type"] == "session_status_updated"
    }
    assert {"waiting_device", "capturing", "evidence_uploaded"} <= statuses


def test_same_manifest_retry_is_idempotent(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    repository.save_session(session)
    ingest_evidence(manifest, repository=repository, clock=lambda: fixed_time)

    status, response = ingest_evidence(
        deepcopy(manifest),
        repository=repository,
        clock=lambda: fixed_time,
    )

    assert status == 200
    assert response["accepted"] is True


def test_new_manifest_is_rejected_after_session_failed(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    session["status"] = "failed"
    session["failure_code"] = "ERR_CAPTURE_FAILED"
    repository.save_session(session)

    with pytest.raises(ApiError) as captured:
        ingest_evidence(
            manifest,
            repository=repository,
            clock=lambda: fixed_time,
        )

    assert captured.value.code == "ERR_EVIDENCE_NOT_ACCEPTED"
    assert repository.load_manifest("session-1") is None


def test_different_manifest_retry_returns_conflict(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    repository.save_session(session)
    ingest_evidence(manifest, repository=repository, clock=lambda: fixed_time)
    changed = deepcopy(manifest)
    changed["sensors"]["temperature_c"] = 26.0

    with pytest.raises(ApiError) as captured:
        ingest_evidence(changed, repository=repository, clock=lambda: fixed_time)

    assert captured.value.code == "ERR_EVIDENCE_CONFLICT"
    assert captured.value.status_code == 409


def test_validation_error_marks_session_failed(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    repository.save_session(session)
    manifest["device_id"] = "other"

    with pytest.raises(ApiError) as captured:
        ingest_evidence(manifest, repository=repository, clock=lambda: fixed_time)

    assert captured.value.code == "ERR_DEVICE_MISMATCH"
    saved = repository.load_session("session-1")
    assert saved["status"] == "failed"
    assert saved["failure_code"] == "ERR_DEVICE_MISMATCH"


def test_matching_manifest_challenge_is_accepted(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    manifest["challenge"] = {
        "instruction_ja": session["challenge_text"],
        "button_count": session["button_count"],
        "voice_code": session["voice_code"],
        "time_limit_seconds": session["time_limit_seconds"],
    }
    repository.save_session(session)

    status, _ = ingest_evidence(
        manifest,
        repository=repository,
        clock=lambda: fixed_time,
    )

    assert status == 200


def test_mismatched_manifest_challenge_marks_session_failed(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
    fixed_time: datetime,
) -> None:
    manifest["challenge"] = {
        "instruction_ja": session["challenge_text"],
        "button_count": 3,
        "voice_code": session["voice_code"],
        "time_limit_seconds": session["time_limit_seconds"],
    }
    repository.save_session(session)

    with pytest.raises(ApiError) as captured:
        ingest_evidence(
            manifest,
            repository=repository,
            clock=lambda: fixed_time,
        )

    assert captured.value.code == "ERR_INVALID_MANIFEST"
    saved = repository.load_session("session-1")
    assert saved["status"] == "failed"


def test_missing_session_returns_not_found(
    repository: LocalJsonRepository,
    manifest: dict[str, object],
) -> None:
    with pytest.raises(ApiError) as captured:
        ingest_evidence(manifest, repository=repository)
    assert captured.value.code == "ERR_SESSION_NOT_FOUND"
    assert captured.value.status_code == 404


def test_azure_http_ingest_can_be_called_directly(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEVICE_API_KEY", "test-device-api-key")
    session["created_at"] = "2000-01-01T00:00:00.000+00:00"
    session["expires_at"] = "2100-01-01T00:00:00.000+00:00"
    repository = LocalJsonRepository(tmp_path)
    repository.save_session(session)
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/api/evidence/ingest",
        headers={
            "content-type": "application/json",
            "X-Device-Api-Key": "test-device-api-key",
        },
        params={},
        route_params={},
        body=json.dumps(manifest).encode(),
    )

    response = function_app.ingest_evidence_http(request)

    assert response.status_code == 200
    payload = json.loads(response.get_body())
    assert payload == {
        "accepted": True,
        "session_id": "session-1",
        "status": "evidence_uploaded",
    }
