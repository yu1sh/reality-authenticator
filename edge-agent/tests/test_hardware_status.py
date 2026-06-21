from __future__ import annotations

from reality_edge.hardware.status import GpioStatusIndicator


class FakeLed:
    def __init__(self) -> None:
        self.events = []

    def on(self) -> None:
        self.events.append("on")

    def off(self) -> None:
        self.events.append("off")

    def close(self) -> None:
        self.events.append("close")


def test_status_indicator_uses_expected_led_patterns() -> None:
    leds = []

    def factory(**kwargs):
        led = FakeLed()
        leds.append((kwargs, led))
        return led

    indicator = GpioStatusIndicator(
        pin=27,
        led_factory=factory,
        sleep=lambda seconds: None,
    )

    indicator.preflight()
    indicator.capturing()
    indicator.success()
    indicator.failure()
    indicator.close()

    assert leds[0][0] == {"pin": 27, "active_high": True}
    active_events = leds[1][1].events
    assert active_events.count("on") == 1 + 3 + 5
    assert active_events[-2:] == ["off", "close"]
