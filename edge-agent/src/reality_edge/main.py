"""Command-line entry point for the Reality Edge Agent."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from reality_core import sha256_file

from .cloud_client import CloudClient, CloudClientError
from .cloud_sync import CloudSyncError, run_cloud_sync
from .config import EdgeConfig
from .dry_run import run_dry_run
from .hardware.button import GpioButtonCapture
from .hardware.camera import RpicamStillCapture
from .hardware.errors import HardwareError
from .hardware.microphone import ArecordMicrophoneCapture
from .hardware.sensors import GroveSerialSensorReader
from .hardware.status import GpioStatusIndicator
from .iot_agent import (
    AzureDeviceTransport,
    IotAgentError,
    IotEdgeAgent,
    ProcessedCommandStore,
)
from .real_capture import RealDeviceCapture


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("time must include a UTC offset")
    return parsed


def _default_fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "dry_run"


def build_parser(config: EdgeConfig | None = None) -> argparse.ArgumentParser:
    config = config or EdgeConfig.from_environment()
    parser = argparse.ArgumentParser(description="Reality Authenticator Edge Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate local evidence without Raspberry Pi hardware",
    )
    parser.add_argument(
        "--real-device",
        action="store_true",
        help="capture evidence from Raspberry Pi hardware",
    )
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument(
        "--cloud-sync",
        action="store_true",
        default=config.cloud_sync_enabled,
        help="send captured evidence through the local Cloud API",
    )
    parser.add_argument(
        "--iot-listen",
        action="store_true",
        help="run as a long-lived IoT Hub command listener",
    )
    parser.add_argument("--device-id", default=config.device_id)
    parser.add_argument("--session-id")
    parser.add_argument("--button-count", type=int)
    parser.add_argument(
        "--output-dir",
        "--evidence-dir",
        dest="output_dir",
        type=Path,
        default=config.evidence_dir,
    )
    parser.add_argument("--fixtures-dir", type=Path, default=_default_fixtures_dir())
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--no-microphone", action="store_true")
    parser.add_argument("--edge-version", default=config.edge_version)
    parser.add_argument(
        "--fixed-time",
        type=_parse_datetime,
        help="testing hook: use one timezone-aware start time",
    )
    return parser


def _real_device_capture(
    *,
    config: EdgeConfig,
    output_dir: Path,
    fixtures_dir: Path,
    edge_version: str,
    no_camera: bool,
    no_microphone: bool,
) -> RealDeviceCapture:
    return RealDeviceCapture(
        output_dir=output_dir,
        fixtures_dir=fixtures_dir,
        button=GpioButtonCapture(
            pin=config.button_gpio,
            debounce_ms=config.button_debounce_ms,
        ),
        sensors=GroveSerialSensorReader(
            port=config.grove_serial_port,
            baud_rate=config.grove_baud_rate,
            startup_delay_seconds=config.grove_startup_delay_seconds,
        ),
        camera=(
            None
            if no_camera
            else RpicamStillCapture(
                command=config.camera_command,
                width=config.camera_width,
                height=config.camera_height,
                timeout_ms=config.camera_timeout_ms,
            )
        ),
        microphone=(
            None
            if no_microphone
            else ArecordMicrophoneCapture(device=config.audio_device)
        ),
        status=GpioStatusIndicator(pin=config.led_gpio),
        audio_duration_seconds=config.audio_duration_seconds,
        edge_version=edge_version,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = EdgeConfig.from_environment()
        args = build_parser(config).parse_args(argv)
        if args.dry_run == args.real_device:
            raise ValueError("select exactly one of --dry-run or --real-device")
        if args.interactive and args.real_device:
            raise ValueError("--interactive requires --dry-run")
        if (args.no_camera or args.no_microphone) and not args.real_device:
            raise ValueError("--no-camera and --no-microphone require --real-device")
        if args.cloud_sync and (args.no_camera or args.no_microphone):
            raise ValueError(
                "--no-camera and --no-microphone cannot be used with --cloud-sync"
            )
        if args.iot_listen and args.cloud_sync:
            raise ValueError("--iot-listen and --cloud-sync cannot be combined")
        if args.iot_listen:
            connection_string = config.iot_hub_device_connection_string
            if not connection_string:
                raise ValueError(
                    "IOT_HUB_DEVICE_CONNECTION_STRING is required for --iot-listen"
                )
            if args.interactive:
                raise ValueError("--interactive cannot be used with --iot-listen")

            if args.real_device:
                real_capture = _real_device_capture(
                    config=config,
                    output_dir=args.output_dir,
                    fixtures_dir=args.fixtures_dir,
                    edge_version=args.edge_version,
                    no_camera=False,
                    no_microphone=False,
                )
                real_capture.preflight()
                print("Real-device preflight: ready")

                def capture_command(
                    session_id: str,
                    challenge: dict[str, object],
                    expires_at: str,
                ) -> Path:
                    print(f"Challenge: {challenge['instruction_ja']}")
                    return real_capture.capture(
                        session_id=session_id,
                        device_id=args.device_id,
                        button_count=int(challenge["button_count"]),
                        challenge=challenge,
                        expires_at=expires_at,
                    )
            else:
                def capture_command(
                    session_id: str,
                    challenge: dict[str, object],
                    expires_at: str,
                ) -> Path:
                    del expires_at
                    return run_dry_run(
                        output_dir=args.output_dir,
                        fixtures_dir=args.fixtures_dir,
                        device_id=args.device_id,
                        session_id=session_id,
                        button_count=int(challenge["button_count"]),
                        interactive=False,
                        edge_version=args.edge_version,
                        challenge=challenge,
                    )

            agent = IotEdgeAgent(
                transport=AzureDeviceTransport.from_connection_string(
                    connection_string
                ),
                device_id=args.device_id,
                capture=capture_command,
                command_store=ProcessedCommandStore(
                    args.output_dir / ".processed-iot-commands.json"
                ),
                heartbeat_seconds=config.iot_heartbeat_seconds,
            )
            print("IoT Hub listener: ready")
            asyncio.run(agent.run())
            return 0
        if args.cloud_sync:
            if args.session_id is not None:
                raise ValueError("--session-id cannot be used with --cloud-sync")
            if args.fixed_time is not None:
                raise ValueError("--fixed-time cannot be used with --cloud-sync")
            if args.button_count is not None:
                raise ValueError("--button-count cannot be used with --cloud-sync")
            if not config.device_api_key:
                raise ValueError("DEVICE_API_KEY is required for cloud sync")

            capture = None
            if args.real_device:
                real_capture = _real_device_capture(
                    config=config,
                    output_dir=args.output_dir,
                    fixtures_dir=args.fixtures_dir,
                    edge_version=args.edge_version,
                    no_camera=False,
                    no_microphone=False,
                )
                real_capture.preflight()
                print("Real-device preflight: ready")
                def capture_real_device(
                    session_id: str,
                    challenge: dict[str, object],
                    expires_at: str,
                ) -> Path:
                    print(f"Challenge: {challenge['instruction_ja']}")
                    return real_capture.capture(
                        session_id=session_id,
                        device_id=args.device_id,
                        button_count=int(challenge["button_count"]),
                        challenge=challenge,
                        expires_at=expires_at,
                    )

                capture = capture_real_device
            result = run_cloud_sync(
                client=CloudClient(
                    api_base_url=config.api_base_url,
                    device_api_key=config.device_api_key,
                ),
                output_dir=args.output_dir,
                fixtures_dir=args.fixtures_dir,
                device_id=args.device_id,
                verify_base_url=config.verify_base_url,
                interactive=args.interactive,
                edge_version=args.edge_version,
                capture=capture,
            )
            print(f"Manifest: {result.manifest_path}")
            print(f"SHA-256: {sha256_file(result.manifest_path)}")
            print(f"Proof ID: {result.proof_id}")
            print(f"Verification URL: {result.verification_url}")
            print(f"QR URL: {result.qr_url}")
            valid = result.verification["valid"] is True
            status = result.verification.get("status")
            if status not in {"VALID", "INVALID", "WARNING"}:
                status = "VALID" if valid else "INVALID"
            print(f"Verification: {status}")
            return 0 if valid else 1

        if args.real_device:
            if args.fixed_time is not None:
                raise ValueError("--fixed-time requires --dry-run")
            real_capture = _real_device_capture(
                config=config,
                output_dir=args.output_dir,
                fixtures_dir=args.fixtures_dir,
                edge_version=args.edge_version,
                no_camera=args.no_camera,
                no_microphone=args.no_microphone,
            )
            real_capture.preflight()
            print("Real-device preflight: ready")
            if real_capture.degraded:
                print("Warning: degraded capture uses media fixtures")
            manifest_path = real_capture.capture(
                session_id=args.session_id,
                device_id=args.device_id,
                button_count=(
                    args.button_count
                    if args.button_count is not None
                    else config.button_count
                ),
                challenge=None,
                expires_at=None,
            )
            print(f"Manifest: {manifest_path}")
            print(f"SHA-256: {sha256_file(manifest_path)}")
            return 0

        clock = (lambda: args.fixed_time) if args.fixed_time else None
        kwargs = {
            "output_dir": args.output_dir,
            "fixtures_dir": args.fixtures_dir,
            "device_id": args.device_id,
            "session_id": args.session_id,
            "button_count": (
                args.button_count
                if args.button_count is not None
                else config.button_count
            ),
            "interactive": args.interactive,
            "edge_version": args.edge_version,
        }
        if clock is not None:
            kwargs["clock"] = clock

        manifest_path = run_dry_run(**kwargs)
        print(f"Manifest: {manifest_path}")
        print(f"SHA-256: {sha256_file(manifest_path)}")
        return 0
    except (CloudClientError, CloudSyncError, HardwareError, IotAgentError) as error:
        print(f"error: {error.code}: {error.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
