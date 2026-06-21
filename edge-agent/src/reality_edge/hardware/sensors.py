"""Grove Beginner Kit USB serial sensor reader."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Any

from .errors import HardwareError

SerialFactory = Callable[..., Any]


def _default_serial_factory(**kwargs: object) -> Any:
    try:
        import serial
    except ImportError as error:
        raise HardwareError(
            "ERR_SENSOR_UNAVAILABLE",
            "pyserial is not installed",
        ) from error
    try:
        return serial.Serial(**kwargs)
    except Exception as error:
        raise HardwareError(
            "ERR_SENSOR_UNAVAILABLE",
            "Grove serial device could not be opened",
        ) from error


class GroveSerialSensorReader:
    def __init__(
        self,
        *,
        port: str,
        baud_rate: int = 115200,
        timeout_seconds: float = 2.0,
        startup_delay_seconds: float = 2.0,
        serial_factory: SerialFactory = _default_serial_factory,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.timeout_seconds = timeout_seconds
        self.startup_delay_seconds = startup_delay_seconds
        self._serial_factory = serial_factory
        self._sleep = sleep
        self._last_values: dict[str, int | float] | None = None
        self.warnings: list[str] = []

    def preflight(self) -> None:
        connection = self._open()
        connection.close()

    def _open(self) -> Any:
        connection = self._serial_factory(
            port=self.port,
            baudrate=self.baud_rate,
            timeout=self.timeout_seconds,
        )
        if self.startup_delay_seconds:
            self._sleep(self.startup_delay_seconds)
        return connection

    def read(self) -> dict[str, int | float]:
        connection = self._open()
        try:
            connection.reset_input_buffer()
            connection.write(b"READ\n")
            connection.flush()
            raw = connection.readline()
        except Exception as error:
            raise HardwareError(
                "ERR_SENSOR_UNAVAILABLE",
                "Grove sensor read failed",
            ) from error
        finally:
            connection.close()

        if not raw:
            raise HardwareError(
                "ERR_SENSOR_UNAVAILABLE",
                "Grove sensor response timed out",
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HardwareError(
                "ERR_SENSOR_UNAVAILABLE",
                "Grove sensor response is invalid JSON",
            ) from error
        if not isinstance(value, dict):
            raise HardwareError(
                "ERR_SENSOR_INVALID",
                "Grove sensor response must be an object",
            )

        sensors: dict[str, int | float] = {}
        for name, sensor_value in value.items():
            if (
                not isinstance(name, str)
                or not name
                or isinstance(sensor_value, bool)
                or not isinstance(sensor_value, (int, float))
                or not math.isfinite(sensor_value)
            ):
                raise HardwareError(
                    "ERR_SENSOR_INVALID",
                    "Grove sensor values must be finite numbers",
                )
            sensors[name] = sensor_value
        if len(sensors) < 2 or all(value == 0 for value in sensors.values()):
            raise HardwareError(
                "ERR_SENSOR_INVALID",
                "Grove sensor values are insufficient or all zero",
            )
        self.warnings = []
        if self._last_values == sensors:
            self.warnings.append("SENSOR_VALUES_UNCHANGED")
        self._last_values = dict(sensors)
        return sensors
