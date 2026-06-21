"""Edge Agent configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _normalized_url(
    value: str,
    name: str,
    *,
    allow_path: bool = True,
) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    try:
        parsed.port
    except ValueError as error:
        raise ValueError(f"{name} must be an HTTP(S) URL") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an HTTP(S) URL")
    if parsed.query or parsed.fragment or (not allow_path and parsed.path):
        raise ValueError(f"{name} must be an HTTP(S) URL")
    return normalized


@dataclass(frozen=True)
class EdgeConfig:
    device_id: str = "raspi-anchor-01"
    evidence_dir: Path = Path("output")
    edge_version: str = "0.1.0"
    button_count: int = 2
    api_base_url: str = "http://localhost:7071/api"
    device_api_key: str | None = None
    verify_base_url: str = "http://localhost:7071"
    cloud_sync_enabled: bool = False
    button_gpio: int = 17
    led_gpio: int = 27
    button_debounce_ms: int = 200
    grove_serial_port: str = "/dev/serial/by-id/replace-with-arduino-device"
    grove_baud_rate: int = 115200
    grove_startup_delay_seconds: float = 2.0
    camera_command: str = "rpicam-still"
    camera_width: int = 1280
    camera_height: int = 720
    camera_timeout_ms: int = 1000
    audio_device: str = "plughw:1,0"
    audio_duration_seconds: int = 8
    iot_hub_device_connection_string: str | None = None
    iot_heartbeat_seconds: int = 60

    @classmethod
    def from_environment(cls) -> "EdgeConfig":
        button_count = int(os.getenv("BUTTON_COUNT", "2"))
        if button_count < 1:
            raise ValueError("BUTTON_COUNT must be at least 1")
        button_gpio = int(os.getenv("BUTTON_GPIO", "17"))
        led_gpio = int(os.getenv("LED_GPIO", "27"))
        debounce_ms = int(os.getenv("BUTTON_DEBOUNCE_MS", "200"))
        grove_baud_rate = int(os.getenv("GROVE_BAUD_RATE", "115200"))
        grove_startup_delay = float(
            os.getenv("GROVE_STARTUP_DELAY_SECONDS", "2")
        )
        camera_width = int(os.getenv("CAMERA_WIDTH", "1280"))
        camera_height = int(os.getenv("CAMERA_HEIGHT", "720"))
        camera_timeout_ms = int(os.getenv("CAMERA_TIMEOUT_MS", "1000"))
        audio_duration = int(os.getenv("AUDIO_DURATION_SECONDS", "8"))
        heartbeat_seconds = int(os.getenv("IOT_HEARTBEAT_SECONDS", "60"))
        if button_gpio < 0 or led_gpio < 0 or button_gpio == led_gpio:
            raise ValueError("BUTTON_GPIO and LED_GPIO must be distinct BCM pins")
        if debounce_ms < 0:
            raise ValueError("BUTTON_DEBOUNCE_MS must not be negative")
        if grove_baud_rate < 1:
            raise ValueError("GROVE_BAUD_RATE must be positive")
        if grove_startup_delay < 0:
            raise ValueError("GROVE_STARTUP_DELAY_SECONDS must not be negative")
        if min(camera_width, camera_height, camera_timeout_ms) < 1:
            raise ValueError("camera dimensions and timeout must be positive")
        if audio_duration < 1:
            raise ValueError("AUDIO_DURATION_SECONDS must be positive")
        if heartbeat_seconds < 5:
            raise ValueError("IOT_HEARTBEAT_SECONDS must be at least 5")

        return cls(
            device_id=os.getenv("DEVICE_ID", "raspi-anchor-01"),
            evidence_dir=Path(os.getenv("EVIDENCE_DIR", "output")),
            edge_version=os.getenv("EDGE_VERSION", "0.1.0"),
            button_count=button_count,
            api_base_url=_normalized_url(
                os.getenv("API_BASE_URL", "http://localhost:7071/api"),
                "API_BASE_URL",
            ),
            device_api_key=os.getenv("DEVICE_API_KEY") or None,
            verify_base_url=_normalized_url(
                os.getenv("VERIFY_BASE_URL", "http://localhost:7071"),
                "VERIFY_BASE_URL",
                allow_path=False,
            ),
            cloud_sync_enabled=_environment_bool("CLOUD_SYNC_ENABLED", False),
            button_gpio=button_gpio,
            led_gpio=led_gpio,
            button_debounce_ms=debounce_ms,
            grove_serial_port=os.getenv(
                "GROVE_SERIAL_PORT",
                "/dev/serial/by-id/replace-with-arduino-device",
            ),
            grove_baud_rate=grove_baud_rate,
            grove_startup_delay_seconds=grove_startup_delay,
            camera_command=os.getenv("CAMERA_COMMAND", "rpicam-still"),
            camera_width=camera_width,
            camera_height=camera_height,
            camera_timeout_ms=camera_timeout_ms,
            audio_device=os.getenv("AUDIO_DEVICE", "plughw:1,0"),
            audio_duration_seconds=audio_duration,
            iot_hub_device_connection_string=(
                os.getenv("IOT_HUB_DEVICE_CONNECTION_STRING") or None
            ),
            iot_heartbeat_seconds=heartbeat_seconds,
        )
