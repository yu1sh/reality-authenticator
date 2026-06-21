import json
import re
from pathlib import Path

import pytest

from reality_core import canonical_json_bytes, sha256_file
from reality_edge.evidence import build_evidence_manifest, write_evidence_bundle


def test_manifest_contains_required_file_metadata(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    audio = tmp_path / "source.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    manifest = build_evidence_manifest(
        session_id="session-1",
        device_id="device-1",
        edge_started_at="2026-06-09T10:00:00.000+09:00",
        edge_finished_at="2026-06-09T10:00:03.000+09:00",
        button_events=[
            {"index": 1, "timestamp": "2026-06-09T10:00:01.000+09:00"}
        ],
        sensors={"temperature_c": 25.6, "light_raw": 734},
        image_path=image,
        audio_path=audio,
        edge_version="0.1.0",
    )

    assert manifest["schema_version"] == "1.0"
    assert manifest["files"]["image"]["content_type"] == "image/jpeg"
    assert manifest["files"]["audio"]["content_type"] == "audio/x-wav"
    assert manifest["files"]["image"]["size_bytes"] == 5
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["files"]["image"]["sha256"])


def test_manifest_includes_optional_challenge(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    audio = tmp_path / "source.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")
    challenge = {
        "instruction_ja": "button twice",
        "button_count": 2,
        "voice_code": "0007",
        "time_limit_seconds": 10,
    }

    manifest = build_evidence_manifest(
        session_id="session-1",
        device_id="device-1",
        edge_started_at="2026-06-09T10:00:00.000+09:00",
        edge_finished_at="2026-06-09T10:00:03.000+09:00",
        button_events=[],
        sensors={"temperature_c": 25.6, "light_raw": 734},
        image_path=image,
        audio_path=audio,
        edge_version="0.1.0",
        challenge=challenge,
    )

    assert manifest["challenge"] == challenge


@pytest.mark.parametrize(
    ("started_at", "finished_at", "message"),
    [
        (
            "not-a-time",
            "2026-06-09T10:00:03.000+09:00",
            "edge_started_at must be an ISO 8601 timestamp",
        ),
        (
            "2026-06-09T10:00:00",
            "2026-06-09T10:00:03",
            "edge_started_at must include a UTC offset",
        ),
        (
            "2026-06-09T10:00:03.000+09:00",
            "2026-06-09T10:00:00.000+09:00",
            "edge_finished_at must not be before edge_started_at",
        ),
    ],
)
def test_manifest_rejects_invalid_timestamps(
    tmp_path: Path,
    started_at: str,
    finished_at: str,
    message: str,
) -> None:
    image = tmp_path / "source.jpg"
    audio = tmp_path / "source.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match=message):
        build_evidence_manifest(
            session_id="session-1",
            device_id="device-1",
            edge_started_at=started_at,
            edge_finished_at=finished_at,
            button_events=[],
            sensors={"temperature_c": 25.6, "light_raw": 734},
            image_path=image,
            audio_path=audio,
            edge_version="0.1.0",
        )


def test_manifest_requires_two_sensor_values(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    audio = tmp_path / "source.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match="at least two sensor values"):
        build_evidence_manifest(
            session_id="session-1",
            device_id="device-1",
            edge_started_at="2026-06-09T10:00:00.000+09:00",
            edge_finished_at="2026-06-09T10:00:03.000+09:00",
            button_events=[],
            sensors={"temperature_c": 25.6},
            image_path=image,
            audio_path=audio,
            edge_version="0.1.0",
        )


def test_bundle_writes_canonical_manifest_and_sidecar(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    audio = tmp_path / "source.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")
    manifest = {
        "schema_version": "1.0",
        "session_id": "session-1",
        "z": 1,
        "a": 2,
    }

    manifest_path = write_evidence_bundle(
        output_dir=tmp_path / "output",
        manifest=manifest,
        image_source=image,
        audio_source=audio,
        log_text="status=completed\n",
    )

    assert manifest_path.read_bytes() == canonical_json_bytes(manifest)
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    sidecar_digest = (manifest_path.parent / "manifest.sha256").read_text(
        encoding="ascii"
    ).split()[0]
    assert sidecar_digest == sha256_file(manifest_path)
