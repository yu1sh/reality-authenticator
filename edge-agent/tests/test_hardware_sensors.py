from __future__ import annotations

import pytest

from reality_edge.hardware.errors import HardwareError
from reality_edge.hardware.sensors import GroveSerialSensorReader


class FakeSerial:
    def __init__(self, line: bytes) -> None:
        self.line = line
        self.writes = []

    def reset_input_buffer(self) -> None:
        pass

    def write(self, value: bytes) -> None:
        self.writes.append(value)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        return self.line

    def close(self) -> None:
        pass


def test_serial_sensor_reader_parses_values_and_warns_when_unchanged() -> None:
    serial_device = FakeSerial(
        b'{"temperature_c":25.6,"humidity_percent":42.8,"light_raw":734}\n'
    )
    reader = GroveSerialSensorReader(
        port="/dev/ttyACM0",
        serial_factory=lambda **kwargs: serial_device,
        sleep=lambda seconds: None,
    )

    first = reader.read()
    second = reader.read()

    assert first["temperature_c"] == 25.6
    assert serial_device.writes == [b"READ\n", b"READ\n"]
    assert reader.warnings == ["SENSOR_VALUES_UNCHANGED"]


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b"", "ERR_SENSOR_UNAVAILABLE"),
        (b"not-json\n", "ERR_SENSOR_UNAVAILABLE"),
        (b'{"temperature_c":0,"humidity_percent":0}\n', "ERR_SENSOR_INVALID"),
        (b'{"temperature_c":25.0}\n', "ERR_SENSOR_INVALID"),
        (b'{"temperature_c":NaN,"humidity_percent":42}\n', "ERR_SENSOR_INVALID"),
    ],
)
def test_serial_sensor_reader_rejects_invalid_responses(
    line: bytes,
    code: str,
) -> None:
    reader = GroveSerialSensorReader(
        port="/dev/ttyACM0",
        serial_factory=lambda **kwargs: FakeSerial(line),
        sleep=lambda seconds: None,
    )

    with pytest.raises(HardwareError) as captured:
        reader.read()

    assert captured.value.code == code
