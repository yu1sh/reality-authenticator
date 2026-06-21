"""Raspberry Pi evidence capture orchestration."""

from __future__ import annotations

import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Protocol
from uuid import uuid4

from .evidence import build_evidence_manifest, write_manifest_artifacts
from .hardware.errors import HardwareError


class ButtonCapture(Protocol):
    def preflight(self) -> None: ...

    def capture(
        self,
        count: int,
        deadline: datetime,
    ) -> list[dict[str, object]]: ...


class SensorReader(Protocol):
    def preflight(self) -> None: ...

    def read(self) -> dict[str, int | float]: ...


class CameraCapture(Protocol):
    def preflight(self) -> None: ...

    def capture(self, path: Path) -> None: ...


class MicrophoneCapture(Protocol):
    def preflight(self) -> None: ...

    def record(self, path: Path, duration_seconds: int) -> None: ...


class StatusIndicator(Protocol):
    def preflight(self) -> None: ...

    def capturing(self) -> None: ...

    def success(self) -> None: ...

    def failure(self) -> None: ...

    def close(self) -> None: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _parse_deadline(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HardwareError(
            "ERR_SESSION_EXPIRED",
            "Session expiry is invalid",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HardwareError(
            "ERR_SESSION_EXPIRED",
            "Session expiry is invalid",
        )
    return parsed


class RealDeviceCapture:
    def __init__(
        self,
        *,
        output_dir: Path,
        fixtures_dir: Path,
        button: ButtonCapture,
        sensors: SensorReader,
        camera: CameraCapture | None,
        microphone: MicrophoneCapture | None,
        status: StatusIndicator,
        audio_duration_seconds: int = 8,
        edge_version: str = "0.1.0",
        clock=utc_now,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.fixtures_dir = Path(fixtures_dir)
        self.button = button
        self.sensors = sensors
        self.camera = camera
        self.microphone = microphone
        self.status = status
        self.audio_duration_seconds = audio_duration_seconds
        self.edge_version = edge_version
        self.clock = clock

    @property
    def degraded(self) -> bool:
        return self.camera is None or self.microphone is None

    def preflight(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.is_dir():
            raise OSError("EVIDENCE_DIR is not a directory")
        self.button.preflight()
        self.sensors.preflight()
        self.status.preflight()
        if self.camera is not None:
            self.camera.preflight()
        elif not (self.fixtures_dir / "image.jpg").is_file():
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "fallback image fixture is missing",
            )
        if self.microphone is not None:
            self.microphone.preflight()
        elif not (self.fixtures_dir / "audio.wav").is_file():
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "fallback audio fixture is missing",
            )

    def capture(
        self,
        *,
        session_id: str | None,
        device_id: str,
        button_count: int,
        challenge: Mapping[str, object] | None,
        expires_at: str | None,
    ) -> Path:
        actual_session_id = session_id or str(uuid4())
        session_dir = self.output_dir / actual_session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        image_path = session_dir / "image.jpg"
        audio_path = session_dir / "audio.wav"
        started_at = self.clock()
        deadline = (
            _parse_deadline(expires_at)
            if expires_at is not None
            else started_at + timedelta(seconds=45)
        )
        if deadline <= started_at:
            self._write_failure(session_dir, "ERR_SESSION_EXPIRED")
            raise HardwareError(
                "ERR_SESSION_EXPIRED",
                "Session expired before capture started",
            )

        self.status.capturing()
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                button_future = executor.submit(
                    self.button.capture,
                    button_count,
                    deadline,
                )
                sensor_future = executor.submit(self.sensors.read)
                camera_future = self._capture_camera(executor, image_path)
                microphone_future = self._capture_microphone(
                    executor,
                    audio_path,
                )
                button_events = button_future.result()
                sensors = sensor_future.result()
                camera_future.result()
                microphone_future.result()

            finished_at = self.clock()
            if finished_at > deadline:
                raise HardwareError(
                    "ERR_SESSION_EXPIRED",
                    "capture finished after Session expiry",
                )
            manifest = build_evidence_manifest(
                session_id=actual_session_id,
                device_id=device_id,
                edge_started_at=_iso8601(started_at),
                edge_finished_at=_iso8601(finished_at),
                button_events=button_events,
                sensors=sensors,
                image_path=image_path,
                audio_path=audio_path,
                edge_version=self.edge_version,
                challenge=challenge,
            )
            mode = "real-device-degraded" if self.degraded else "real-device"
            sensor_warnings = getattr(self.sensors, "warnings", [])
            warning_lines = "".join(
                f"warning={warning}\n" for warning in sensor_warnings
            )
            manifest_path = write_manifest_artifacts(
                session_dir=session_dir,
                manifest=manifest,
                log_text=(
                    f"session_id={actual_session_id}\n"
                    f"device_id={device_id}\n"
                    f"mode={mode}\n"
                    f"button_events={len(button_events)}\n"
                    f"camera={'fixture' if self.camera is None else 'hardware'}\n"
                    f"microphone={'fixture' if self.microphone is None else 'hardware'}\n"
                    f"{warning_lines}"
                    "status=completed\n"
                ),
            )
            self.status.success()
            return manifest_path
        except HardwareError as error:
            self._write_failure(session_dir, error.code)
            self.status.failure()
            raise
        except Exception as error:
            self._write_failure(session_dir, "ERR_CAPTURE_FAILED")
            self.status.failure()
            raise HardwareError(
                "ERR_CAPTURE_FAILED",
                "real-device capture failed",
            ) from error
        finally:
            self.status.close()

    def _capture_camera(
        self,
        executor: ThreadPoolExecutor,
        path: Path,
    ) -> Future[None]:
        if self.camera is not None:
            return executor.submit(self.camera.capture, path)
        return executor.submit(
            shutil.copyfile,
            self.fixtures_dir / "image.jpg",
            path,
        )

    def _capture_microphone(
        self,
        executor: ThreadPoolExecutor,
        path: Path,
    ) -> Future[None]:
        if self.microphone is not None:
            return executor.submit(
                self.microphone.record,
                path,
                self.audio_duration_seconds,
            )
        return executor.submit(
            shutil.copyfile,
            self.fixtures_dir / "audio.wav",
            path,
        )

    @staticmethod
    def _write_failure(session_dir: Path, code: str) -> None:
        with (session_dir / "edge.log").open("a", encoding="utf-8") as log:
            log.write("mode=real-device\n")
            log.write("status=failed\n")
            log.write(f"failure_code={code}\n")
