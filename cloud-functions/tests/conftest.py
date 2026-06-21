from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

CLOUD_FUNCTIONS_ROOT = Path(__file__).resolve().parents[1]
if str(CLOUD_FUNCTIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(CLOUD_FUNCTIONS_ROOT))

from reality_cloud.config import CloudConfig
from reality_cloud.storage import LocalJsonRepository


@pytest.fixture
def fixed_time() -> datetime:
    return datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc)


@pytest.fixture
def config(tmp_path: Path) -> CloudConfig:
    return CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path / "data",
        device_api_key="test-device-api-key",
        stub_signing_secret="test-signing-secret",
        signature_key_id="local-stub-v1",
        public_web_base_url="http://localhost:7071",
    )


@pytest.fixture
def repository(config: CloudConfig) -> LocalJsonRepository:
    return LocalJsonRepository(config.local_data_dir)


@pytest.fixture
def session() -> dict[str, object]:
    return {
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "status": "challenge_issued",
        "challenge_nonce": "nonce-1",
        "challenge_text": "challenge",
        "button_count": 2,
        "voice_code": "0007",
        "time_limit_seconds": 10,
        "created_at": "2026-06-09T01:00:00.000+00:00",
        "expires_at": "2026-06-09T01:00:15.000+00:00",
        "failure_code": None,
    }


@pytest.fixture
def manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "edge_started_at": "2026-06-09T01:00:01.000+00:00",
        "edge_finished_at": "2026-06-09T01:00:03.000+00:00",
        "button_events": [
            {"index": 1, "timestamp": "2026-06-09T01:00:01.500+00:00"},
            {"index": 2, "timestamp": "2026-06-09T01:00:02.500+00:00"},
        ],
        "sensors": {
            "temperature_c": 25.6,
            "humidity_percent": 42.8,
        },
        "files": {
            "image": {
                "blob_path": "evidence/session-1/image.jpg",
                "sha256": "a" * 64,
                "content_type": "image/jpeg",
                "size_bytes": 292,
            },
            "audio": {
                "blob_path": "evidence/session-1/audio.wav",
                "sha256": "b" * 64,
                "content_type": "audio/x-wav",
                "size_bytes": 4078,
            },
        },
        "edge_version": "0.1.0",
    }


@pytest.fixture
def accepted_session(session: dict[str, object]) -> dict[str, object]:
    session["status"] = "evidence_uploaded"
    return session
