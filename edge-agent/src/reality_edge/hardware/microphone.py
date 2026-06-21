"""USB microphone capture using ALSA arecord."""

from __future__ import annotations

import shutil
import subprocess
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

from .errors import HardwareError

Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_wav(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as audio:
            valid = (
                audio.getnchannels() == 1
                and audio.getsampwidth() == 2
                and audio.getframerate() == 16000
                and audio.getnframes() > 0
            )
    except (OSError, EOFError, wave.Error) as error:
        raise HardwareError(
            "ERR_MICROPHONE_CAPTURE",
            "microphone output is not a valid WAV",
        ) from error
    if not valid:
        raise HardwareError(
            "ERR_MICROPHONE_CAPTURE",
            "microphone WAV format is invalid",
        )


class ArecordMicrophoneCapture:
    def __init__(
        self,
        *,
        device: str,
        command: str = "arecord",
        runner: Runner = subprocess.run,
        command_lookup: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.device = device
        self.command = command
        self._runner = runner
        self._command_lookup = command_lookup

    def preflight(self) -> None:
        if self._command_lookup(self.command) is None:
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "arecord command was not found",
            )
        try:
            result = self._runner(
                (self.command, "--list-devices"),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "microphone diagnostic failed",
            ) from error
        if result.returncode != 0 or not (result.stdout or result.stderr).strip():
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "no recording device was detected",
            )

    def record(self, path: Path, duration_seconds: int) -> None:
        command: Sequence[str] = (
            self.command,
            "--device",
            self.device,
            "--format",
            "S16_LE",
            "--rate",
            "16000",
            "--channels",
            "1",
            "--duration",
            str(duration_seconds),
            "--file-type",
            "wav",
            str(path),
        )
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=duration_seconds + 10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "microphone command failed",
            ) from error
        if result.returncode != 0:
            raise HardwareError(
                "ERR_MICROPHONE_CAPTURE",
                "microphone command returned an error",
            )
        validate_wav(path)
