"""Pi Camera still capture using rpicam-still."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from .errors import HardwareError

Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_jpeg(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise HardwareError(
            "ERR_CAMERA_CAPTURE",
            "camera output could not be read",
        ) from error
    if len(data) < 128 or not data.startswith(b"\xff\xd8") or not data.endswith(
        b"\xff\xd9"
    ):
        raise HardwareError(
            "ERR_CAMERA_CAPTURE",
            "camera output is not a valid JPEG",
        )


class RpicamStillCapture:
    def __init__(
        self,
        *,
        command: str = "rpicam-still",
        width: int = 1280,
        height: int = 720,
        timeout_ms: int = 1000,
        runner: Runner = subprocess.run,
        command_lookup: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.command = command
        self.width = width
        self.height = height
        self.timeout_ms = timeout_ms
        self._runner = runner
        self._command_lookup = command_lookup

    def preflight(self) -> None:
        if self._command_lookup(self.command) is None:
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "rpicam-still command was not found",
            )
        try:
            result = self._runner(
                (self.command, "--list-cameras"),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "camera diagnostic failed",
            ) from error
        diagnostic = f"{result.stdout}\n{result.stderr}".strip().lower()
        if (
            result.returncode != 0
            or not diagnostic
            or "no cameras available" in diagnostic
        ):
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "no camera was detected",
            )

    def capture(self, path: Path) -> None:
        command: Sequence[str] = (
            self.command,
            "--output",
            str(path),
            "--width",
            str(self.width),
            "--height",
            str(self.height),
            "--timeout",
            str(self.timeout_ms),
            "--nopreview",
        )
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=max(10, self.timeout_ms / 1000 + 10),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "camera command failed",
            ) from error
        if result.returncode != 0:
            raise HardwareError(
                "ERR_CAMERA_CAPTURE",
                "camera command returned an error",
            )
        validate_jpeg(path)
