"""GPIO button capture."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .errors import HardwareError

ButtonFactory = Callable[..., Any]
Clock = Callable[[], datetime]


def _default_button_factory(**kwargs: object) -> Any:
    try:
        from gpiozero import Button
    except ImportError as error:
        raise HardwareError(
            "ERR_GPIO_UNAVAILABLE",
            "GPIO Zero is not installed",
        ) from error
    try:
        return Button(**kwargs)
    except Exception as error:
        raise HardwareError(
            "ERR_GPIO_UNAVAILABLE",
            "button GPIO could not be opened",
        ) from error


def _iso8601(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class GpioButtonCapture:
    def __init__(
        self,
        *,
        pin: int,
        debounce_ms: int,
        button_factory: ButtonFactory = _default_button_factory,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.pin = pin
        self.debounce_ms = debounce_ms
        self._button_factory = button_factory
        self._clock = clock

    def preflight(self) -> None:
        button = self._open()
        button.close()

    def _open(self) -> Any:
        return self._button_factory(
            pin=self.pin,
            pull_up=True,
            bounce_time=self.debounce_ms / 1000,
        )

    def capture(
        self,
        count: int,
        deadline: datetime,
    ) -> list[dict[str, object]]:
        if count < 1:
            raise ValueError("button count must be at least 1")
        button = self._open()
        events: list[dict[str, object]] = []
        try:
            for index in range(1, count + 1):
                remaining = (deadline - self._clock()).total_seconds()
                if remaining <= 0 or not button.wait_for_press(timeout=remaining):
                    raise HardwareError(
                        "ERR_BUTTON_TIMEOUT",
                        "button challenge timed out",
                    )
                pressed_at = self._clock()
                if pressed_at > deadline:
                    raise HardwareError(
                        "ERR_BUTTON_TIMEOUT",
                        "button challenge timed out",
                    )
                events.append(
                    {"index": index, "timestamp": _iso8601(pressed_at)}
                )
                if not button.wait_for_release(timeout=1):
                    raise HardwareError(
                        "ERR_BUTTON_TIMEOUT",
                        "button was not released",
                    )
        finally:
            button.close()
        return events
