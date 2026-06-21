from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reality_edge.hardware.button import GpioButtonCapture
from reality_edge.hardware.errors import HardwareError


class FakeButton:
    def __init__(self, presses: list[bool]) -> None:
        self.presses = iter(presses)
        self.closed = False

    def wait_for_press(self, timeout: float) -> bool:
        return next(self.presses)

    def wait_for_release(self, timeout: float) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def test_button_capture_records_sequential_events_and_debounce() -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    times = iter(
        [
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=1),
            start + timedelta(seconds=2),
        ]
    )
    created = []

    def factory(**kwargs):
        created.append(kwargs)
        return FakeButton([True, True])

    capture = GpioButtonCapture(
        pin=17,
        debounce_ms=200,
        button_factory=factory,
        clock=lambda: next(times),
    )

    events = capture.capture(2, start + timedelta(seconds=10))

    assert [event["index"] for event in events] == [1, 2]
    assert created[0]["pull_up"] is True
    assert created[0]["bounce_time"] == 0.2


def test_button_capture_times_out() -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    capture = GpioButtonCapture(
        pin=17,
        debounce_ms=200,
        button_factory=lambda **kwargs: FakeButton([False]),
        clock=lambda: start,
    )

    with pytest.raises(HardwareError) as captured:
        capture.capture(1, start + timedelta(seconds=1))

    assert captured.value.code == "ERR_BUTTON_TIMEOUT"

