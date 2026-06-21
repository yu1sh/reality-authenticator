"""Evidence Manifest construction and bundle persistence."""

from __future__ import annotations

import mimetypes
import shutil
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from reality_core import canonical_json_bytes, sha256_bytes, sha256_file


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _file_metadata(path: Path, blob_path: str) -> dict[str, object]:
    content_type, _ = mimetypes.guess_type(path.name)
    if content_type is None:
        content_type = "application/octet-stream"
    return {
        "blob_path": blob_path,
        "sha256": sha256_file(path),
        "content_type": content_type,
        "size_bytes": path.stat().st_size,
    }


def build_evidence_manifest(
    *,
    session_id: str,
    device_id: str,
    edge_started_at: str,
    edge_finished_at: str,
    button_events: Sequence[Mapping[str, object]],
    sensors: Mapping[str, int | float],
    image_path: Path,
    audio_path: Path,
    edge_version: str,
    challenge: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a schema version 1.0 Evidence Manifest."""

    if not session_id:
        raise ValueError("session_id is required")
    if not device_id:
        raise ValueError("device_id is required")
    if not edge_started_at or not edge_finished_at:
        raise ValueError("edge start and finish timestamps are required")
    started_at = _parse_timestamp(edge_started_at, "edge_started_at")
    finished_at = _parse_timestamp(edge_finished_at, "edge_finished_at")
    if finished_at < started_at:
        raise ValueError("edge_finished_at must not be before edge_started_at")
    if len(sensors) < 2:
        raise ValueError("at least two sensor values are required")

    image_path = Path(image_path)
    audio_path = Path(audio_path)
    blob_root = f"evidence/{session_id}"

    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "session_id": session_id,
        "device_id": device_id,
        "edge_started_at": edge_started_at,
        "edge_finished_at": edge_finished_at,
        "button_events": [dict(event) for event in button_events],
        "sensors": dict(sensors),
        "files": {
            "image": _file_metadata(image_path, f"{blob_root}/image.jpg"),
            "audio": _file_metadata(audio_path, f"{blob_root}/audio.wav"),
        },
        "edge_version": edge_version,
    }
    if challenge is not None:
        manifest["challenge"] = dict(challenge)
    return manifest


def write_evidence_bundle(
    *,
    output_dir: Path,
    manifest: Mapping[str, object],
    image_source: Path,
    audio_source: Path,
    log_text: str,
) -> Path:
    """Write evidence files and return the generated manifest path."""

    session_id = str(manifest["session_id"])
    session_dir = Path(output_dir) / session_id
    session_dir.mkdir(parents=True, exist_ok=False)

    shutil.copyfile(image_source, session_dir / "image.jpg")
    shutil.copyfile(audio_source, session_dir / "audio.wav")

    return write_manifest_artifacts(
        session_dir=session_dir,
        manifest=manifest,
        log_text=log_text,
    )


def write_manifest_artifacts(
    *,
    session_dir: Path,
    manifest: Mapping[str, object],
    log_text: str,
) -> Path:
    """Write canonical Manifest artifacts into an existing Session directory."""

    manifest_bytes = canonical_json_bytes(dict(manifest))
    manifest_path = Path(session_dir) / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    (Path(session_dir) / "manifest.sha256").write_text(
        f"{sha256_bytes(manifest_bytes)}  manifest.json\n",
        encoding="ascii",
    )
    (Path(session_dir) / "edge.log").write_text(log_text, encoding="utf-8")
    return manifest_path
