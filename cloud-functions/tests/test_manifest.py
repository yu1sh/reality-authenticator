from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from reality_cloud.errors import ApiError
from reality_cloud.manifest import validate_manifest


def _assert_error(
    manifest: dict[str, object],
    session: dict[str, object],
    fixed_time: datetime,
    code: str,
) -> None:
    with pytest.raises(ApiError) as captured:
        validate_manifest(manifest, session, now=fixed_time)
    assert captured.value.code == code


def test_valid_phase_1_manifest_is_accepted(
    manifest: dict[str, object],
    session: dict[str, object],
    fixed_time: datetime,
) -> None:
    validate_manifest(manifest, session, now=fixed_time)


def test_audio_wav_alias_is_accepted(
    manifest: dict[str, object],
    session: dict[str, object],
    fixed_time: datetime,
) -> None:
    manifest["files"]["audio"]["content_type"] = "audio/wav"
    validate_manifest(manifest, session, now=fixed_time)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(schema_version="2.0"), "ERR_SCHEMA_VERSION"),
        (lambda value: value.update(device_id="other"), "ERR_DEVICE_MISMATCH"),
        (
            lambda value: value.update(edge_started_at="2026-06-09T01:00:01"),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["button_events"].pop(),
            "ERR_BUTTON_COUNT",
        ),
        (
            lambda value: value.update(sensors={"temperature_c": 25.6}),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value.update(
                sensors={"temperature_c": 25.6, "humidity_percent": float("nan")}
            ),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value.update(
                sensors={"temperature_c": 25.6, "occupied": True}
            ),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["files"].pop("image"),
            "ERR_FILE_MISSING",
        ),
        (
            lambda value: value["files"]["image"].update(sha256="ABC"),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["files"]["audio"].update(size_bytes=0),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["files"]["audio"].update(content_type="audio/mpeg"),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["files"]["image"].update(
                blob_path="../image.jpg"
            ),
            "ERR_INVALID_MANIFEST",
        ),
        (
            lambda value: value["button_events"][1].update(index=3),
            "ERR_BUTTON_COUNT",
        ),
    ],
)
def test_invalid_manifests_are_rejected(
    manifest: dict[str, object],
    session: dict[str, object],
    fixed_time: datetime,
    mutation,
    code: str,
) -> None:
    candidate = deepcopy(manifest)
    mutation(candidate)
    _assert_error(candidate, session, fixed_time, code)


def test_event_outside_capture_range_is_rejected(
    manifest: dict[str, object],
    session: dict[str, object],
    fixed_time: datetime,
) -> None:
    manifest["button_events"][0]["timestamp"] = "2026-06-09T01:00:00.500+00:00"
    _assert_error(manifest, session, fixed_time, "ERR_BUTTON_COUNT")


def test_expired_session_is_rejected(
    manifest: dict[str, object],
    session: dict[str, object],
) -> None:
    expired_now = datetime.fromisoformat("2026-06-09T01:00:16+00:00")
    _assert_error(manifest, session, expired_now, "ERR_SESSION_EXPIRED")
