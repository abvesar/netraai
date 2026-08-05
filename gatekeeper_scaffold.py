from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

try:
    import RPi.GPIO as GPIO  # type: ignore[import-not-found]
except Exception:
    GPIO = None


class AlcoholSensor(Protocol):
    def read_value(self) -> float:
        """Return the latest alcohol sensor reading as a normalized value."""


class AccessControlOutput(Protocol):
    def allow_access(self) -> None:
        """Handle the allowed state in a non-vehicle-specific way."""

    def deny_access(self) -> None:
        """Handle the denied state in a non-vehicle-specific way."""


@dataclass(frozen=True)
class GatekeeperConfig:
    threshold: float = 0.5


@dataclass(frozen=True)
class RaspberryPiRelayConfig:
    relay_pin: int = 17
    active_high: bool = True
    dry_run: bool = True


class MockAlcoholSensor:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def read_value(self) -> float:
        return self.value


class LoggingAccessControl:
    def allow_access(self) -> None:
        print("ACCESS_ALLOWED")

    def deny_access(self) -> None:
        print("ACCESS_DENIED")


class RaspberryPiRelayOutput:
    def __init__(self, config: RaspberryPiRelayConfig) -> None:
        self.config = config
        self._enabled = GPIO is not None and not self.config.dry_run

        if self._enabled:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.relay_pin, GPIO.OUT)

    def allow_access(self) -> None:
        state = 1 if self.config.active_high else 0
        self._write(state=state, label="ACCESS_ALLOWED")

    def deny_access(self) -> None:
        state = 0 if self.config.active_high else 1
        self._write(state=state, label="ACCESS_DENIED")

    def cleanup(self) -> None:
        if self._enabled:
            GPIO.cleanup(self.config.relay_pin)

    def _write(self, state: int, label: str) -> None:
        state_label = "HIGH" if state else "LOW"

        if self._enabled:
            GPIO.output(self.config.relay_pin, state)
            print(f"{label} relay={state_label} pin={self.config.relay_pin}")
            return

        print(f"{label} relay={state_label} pin={self.config.relay_pin} dry_run=True")


def sobriety_check(
    sensor_value: float,
    threshold: float,
    output: AccessControlOutput,
) -> bool:
    if sensor_value < threshold:
        output.allow_access()
        return True

    output.deny_access()
    return False


class Gatekeeper:
    def __init__(
        self,
        sensor: AlcoholSensor,
        output: AccessControlOutput,
        config: GatekeeperConfig,
    ) -> None:
        self.sensor = sensor
        self.output = output
        self.config = config

    def evaluate(self) -> bool:
        sensor_value = self.sensor.read_value()
        return sobriety_check(
            sensor_value=sensor_value,
            threshold=self.config.threshold,
            output=self.output,
        )


def main() -> None:
    sensor = MockAlcoholSensor(value=0.42)
    output = RaspberryPiRelayOutput(config=RaspberryPiRelayConfig(dry_run=True))
    gatekeeper = Gatekeeper(sensor=sensor, output=output, config=GatekeeperConfig())
    result = gatekeeper.evaluate()
    print(f"decision={result}")


if __name__ == "__main__":
    main()
