from __future__ import annotations

import json
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reality_edge.hardware.errors import HardwareError
from reality_edge.real_capture import RealDeviceCapture


class FakeButton:
    def preflight(self) -> None:
        pass

    def capture(self, count, deadline):
        start = deadline - timedelta(seconds=10)
        return [
            {
                "index": index,
                "timestamp": (
                    start + timedelta(seconds=index)
                ).isoformat(timespec="milliseconds"),
            }
            for index in range(1, count + 1)
        ]


class FakeSensors:
    warnings = ["SENSOR_VALUES_UNCHANGED"]

    def preflight(self) -> None:
        pass

    def read(self):
        return {"temperature_c": 25.6, "humidity_percent": 42.8}


class FailingSensors(FakeSensors):
    def read(self):
        raise HardwareError("ERR_SENSOR_UNAVAILABLE", "no serial")


class FakeCamera:
    def preflight(self) -> None:
        pass

    def capture(self, path: Path) -> None:
        path.write_bytes(b"\xff\xd8" + b"x" * 128 + b"\xff\xd9")


class FakeMicrophone:
    def preflight(self) -> None:
        pass

    def record(self, path: Path, duration_seconds: int) -> None:
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 160)


class FakeStatus:
    def __init__(self) -> None:
        self.events = []

    def preflight(self) -> None:
        self.events.append("preflight")

    def capturing(self) -> None:
        self.events.append("capturing")

    def success(self) -> None:
        self.events.append("success")

    def failure(self) -> None:
        self.events.append("failure")

    def close(self) -> None:
        self.events.append("close")


def test_real_capture_builds_manifest_from_hardware(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    times = iter([start, start + timedelta(seconds=8)])
    status = FakeStatus()
    capture = RealDeviceCapture(
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        button=FakeButton(),
        sensors=FakeSensors(),
        camera=FakeCamera(),
        microphone=FakeMicrophone(),
        status=status,
        clock=lambda: next(times),
    )
    challenge = {
        "instruction_ja": "challenge",
        "button_count": 2,
        "voice_code": "0007",
        "time_limit_seconds": 30,
    }

    capture.preflight()
    manifest_path = capture.capture(
        session_id="session-1",
        device_id="device-1",
        button_count=2,
        challenge=challenge,
        expires_at=(start + timedelta(seconds=45)).isoformat(),
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["challenge"] == challenge
    assert len(manifest["button_events"]) == 2
    assert manifest["files"]["image"]["size_bytes"] > 0
    assert status.events == ["preflight", "capturing", "success", "close"]
    assert "warning=SENSOR_VALUES_UNCHANGED" in (
        manifest_path.parent / "edge.log"
    ).read_text()


def test_real_capture_preserves_failure_log(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    status = FakeStatus()
    capture = RealDeviceCapture(
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        button=FakeButton(),
        sensors=FailingSensors(),
        camera=FakeCamera(),
        microphone=FakeMicrophone(),
        status=status,
        clock=lambda: start,
    )

    with pytest.raises(HardwareError) as captured:
        capture.capture(
            session_id="session-failed",
            device_id="device-1",
            button_count=1,
            challenge=None,
            expires_at=(start + timedelta(seconds=45)).isoformat(),
        )

    assert captured.value.code == "ERR_SENSOR_UNAVAILABLE"
    log = (tmp_path / "session-failed" / "edge.log").read_text()
    assert "failure_code=ERR_SENSOR_UNAVAILABLE" in log
    assert status.events[-2:] == ["failure", "close"]


def test_degraded_real_capture_uses_fixtures(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    times = iter([start, start + timedelta(seconds=2)])
    capture = RealDeviceCapture(
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        button=FakeButton(),
        sensors=FakeSensors(),
        camera=None,
        microphone=None,
        status=FakeStatus(),
        clock=lambda: next(times),
    )

    capture.preflight()
    manifest_path = capture.capture(
        session_id="degraded",
        device_id="device-1",
        button_count=1,
        challenge=None,
        expires_at=None,
    )

    log = (manifest_path.parent / "edge.log").read_text()
    assert "mode=real-device-degraded" in log
    assert "camera=fixture" in log
    assert "microphone=fixture" in log
    assert (manifest_path.parent / "image.jpg").read_bytes() == (
        fixtures_dir / "image.jpg"
    ).read_bytes()
