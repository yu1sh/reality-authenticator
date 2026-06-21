from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from reality_edge.hardware.camera import RpicamStillCapture
from reality_edge.hardware.errors import HardwareError
from reality_edge.hardware.microphone import ArecordMicrophoneCapture


def test_camera_runs_expected_command_and_validates_jpeg(tmp_path: Path) -> None:
    commands = []
    output = tmp_path / "image.jpg"

    def runner(command, **kwargs):
        commands.append(tuple(command))
        if "--list-cameras" in command:
            return subprocess.CompletedProcess(command, 0, "Available cameras", "")
        output.write_bytes(b"\xff\xd8" + b"x" * 128 + b"\xff\xd9")
        return subprocess.CompletedProcess(command, 0, "", "")

    camera = RpicamStillCapture(
        runner=runner,
        command_lookup=lambda command: f"/usr/bin/{command}",
    )
    camera.preflight()
    camera.capture(output)

    assert commands[0] == ("rpicam-still", "--list-cameras")
    assert "--nopreview" in commands[1]
    assert output.is_file()


def test_camera_rejects_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "image.jpg"
    output.write_bytes(b"")
    camera = RpicamStillCapture(
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
        command_lookup=lambda command: f"/usr/bin/{command}",
    )

    with pytest.raises(HardwareError) as captured:
        camera.capture(output)

    assert captured.value.code == "ERR_CAMERA_CAPTURE"


def test_camera_preflight_rejects_no_detected_cameras() -> None:
    camera = RpicamStillCapture(
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "No cameras available!", ""
        ),
        command_lookup=lambda command: f"/usr/bin/{command}",
    )

    with pytest.raises(HardwareError) as captured:
        camera.preflight()

    assert captured.value.code == "ERR_CAMERA_CAPTURE"


def test_microphone_runs_arecord_and_validates_wav(tmp_path: Path) -> None:
    commands = []
    output = tmp_path / "audio.wav"

    def runner(command, **kwargs):
        commands.append(tuple(command))
        if "--list-devices" in command:
            return subprocess.CompletedProcess(command, 0, "card 1: USB", "")
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 160)
        return subprocess.CompletedProcess(command, 0, "", "")

    microphone = ArecordMicrophoneCapture(
        device="plughw:1,0",
        runner=runner,
        command_lookup=lambda command: f"/usr/bin/{command}",
    )
    microphone.preflight()
    microphone.record(output, 8)

    assert commands[0] == ("arecord", "--list-devices")
    assert "--rate" in commands[1]
    assert "16000" in commands[1]


def test_microphone_rejects_invalid_wav(tmp_path: Path) -> None:
    output = tmp_path / "audio.wav"
    output.write_bytes(b"")
    microphone = ArecordMicrophoneCapture(
        device="default",
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
        command_lookup=lambda command: f"/usr/bin/{command}",
    )

    with pytest.raises(HardwareError) as captured:
        microphone.record(output, 1)

    assert captured.value.code == "ERR_MICROPHONE_CAPTURE"
