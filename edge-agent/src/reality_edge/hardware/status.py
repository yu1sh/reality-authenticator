"""GPIO status LED."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .errors import HardwareError

LedFactory = Callable[..., Any]


def _default_led_factory(**kwargs: object) -> Any:
    try:
        from gpiozero import LED
    except ImportError as error:
        raise HardwareError(
            "ERR_GPIO_UNAVAILABLE",
            "GPIO Zero is not installed",
        ) from error
    try:
        return LED(**kwargs)
    except Exception as error:
        raise HardwareError(
            "ERR_GPIO_UNAVAILABLE",
            "LED GPIO could not be opened",
        ) from error


class GpioStatusIndicator:
    def __init__(
        self,
        *,
        pin: int,
        led_factory: LedFactory = _default_led_factory,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.pin = pin
        self._led_factory = led_factory
        self._sleep = sleep
        self._led: Any | None = None

    def preflight(self) -> None:
        self._open().off()
        self.close()

    def _open(self) -> Any:
        if self._led is None:
            self._led = self._led_factory(pin=self.pin, active_high=True)
        return self._led

    def capturing(self) -> None:
        self._open().on()

    def success(self) -> None:
        self._blink(3, 0.2)

    def failure(self) -> None:
        self._blink(5, 0.1)

    def close(self) -> None:
        if self._led is not None:
            self._led.off()
            self._led.close()
            self._led = None

    def _blink(self, count: int, interval: float) -> None:
        led = self._open()
        led.off()
        for _ in range(count):
            led.on()
            self._sleep(interval)
            led.off()
            self._sleep(interval)
