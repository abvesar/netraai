from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from dataclasses import dataclass
from typing import Optional, Protocol

try:
    import RPi.GPIO as GPIO  # type: ignore[import-not-found]
except Exception:
    GPIO = None


class AnalogVoltageReader(Protocol):
    def read_voltage(self) -> float:
        """Read and return current MQ-3 analog output voltage in volts."""


@dataclass(frozen=True)
class GatekeeperConfig:
    alcohol_threshold_brac: float = 0.02
    brac_per_volt_delta: float = 0.04
    burn_in_hours: int = 24
    sample_interval_seconds: float = 0.5
    valid_voltage_min: float = 0.0
    valid_voltage_max: float = 5.0
    burn_in_state_file: str = "artifacts/mq3_burn_in_state.json"
    calibration_state_file: str = "artifacts/mq3_calibration_state.json"


@dataclass(frozen=True)
class RelayConfig:
    relay_pin: int = 17
    active_high: bool = True
    dry_run: bool = True


class MockAnalogVoltageReader:
    """Useful for local simulation without hardware."""

    def __init__(self, fixed_voltage: float) -> None:
        self.fixed_voltage = fixed_voltage

    def read_voltage(self) -> float:
        return self.fixed_voltage


class ADS1115VoltageReader:
    """
    ADC reader for MQ-3 analog output via ADS1115.
    Raspberry Pi has no native analog input, so an external ADC is required.
    """

    def __init__(self, channel: int = 0, gain: int = 1) -> None:
        try:
            import board  # type: ignore[import-not-found]
            import busio  # type: ignore[import-not-found]
            import adafruit_ads1x15.ads1115 as ADS  # type: ignore[import-not-found]
            from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(
                "ADS1115 dependencies missing. Install: adafruit-circuitpython-ads1x15"
            ) from exc

        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = gain

        channel_map = {
            0: ADS.P0,
            1: ADS.P1,
            2: ADS.P2,
            3: ADS.P3,
        }
        if channel not in channel_map:
            raise ValueError("ADS1115 channel must be one of: 0, 1, 2, 3")

        self._channel = AnalogIn(ads, channel_map[channel])

    def read_voltage(self) -> float:
        return float(self._channel.voltage)


class RelayController:
    """Controls a relay that gates ignition/starter line. Fail-safe default is OFF."""

    def __init__(self, config: RelayConfig) -> None:
        self.config = config
        self._enabled = GPIO is not None and not self.config.dry_run

        if self._enabled:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.relay_pin, GPIO.OUT)

        self.set_off()

    def set_on(self) -> None:
        state = 1 if self.config.active_high else 0
        self._write(state=state, label="RELAY_ON")

    def set_off(self) -> None:
        state = 0 if self.config.active_high else 1
        self._write(state=state, label="RELAY_OFF")

    def cleanup(self) -> None:
        if self._enabled:
            GPIO.cleanup(self.config.relay_pin)

    def _write(self, state: int, label: str) -> None:
        level = "HIGH" if state else "LOW"
        if self._enabled:
            GPIO.output(self.config.relay_pin, state)
        print(f"{label} pin={self.config.relay_pin} level={level} dry_run={not self._enabled}")


class MQ3Gatekeeper:
    def __init__(
        self,
        reader: AnalogVoltageReader,
        relay: RelayController,
        config: GatekeeperConfig,
    ) -> None:
        self.reader = reader
        self.relay = relay
        self.config = config
        self._started_at_epoch = self._load_or_create_burn_in_start_epoch(
            state_path=Path(self.config.burn_in_state_file)
        )
        self._baseline_voltage = self._load_baseline_voltage(Path(self.config.calibration_state_file))

    def _load_or_create_burn_in_start_epoch(self, state_path: Path) -> float:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if state_path.exists():
            try:
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                started_at = float(raw["burn_in_started_at_epoch_s"])
                return started_at
            except Exception:
                pass

        started_at = time.time()
        payload = {"burn_in_started_at_epoch_s": started_at}
        state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return started_at

    def _load_baseline_voltage(self, state_path: Path) -> Optional[float]:
        if not state_path.exists():
            return None
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            return float(raw["clean_air_baseline_voltage"]) 
        except Exception:
            return None

    def estimate_brac(self, voltage: float) -> Optional[float]:
        if self._baseline_voltage is None:
            return None
        delta = max(0.0, voltage - self._baseline_voltage)
        return delta * self.config.brac_per_volt_delta

    def is_burn_in_complete(self) -> bool:
        burn_in_seconds = self.config.burn_in_hours * 3600
        elapsed = time.time() - self._started_at_epoch
        return elapsed >= burn_in_seconds

    def evaluate_once(self) -> bool:
        """
        Returns True when ignition is allowed.
        Returns False when ignition is blocked.
        """
        if not self.is_burn_in_complete():
            self.relay.set_off()
            print("decision=DENY reason=sensor_burn_in_incomplete")
            return False

        try:
            voltage = self.reader.read_voltage()
        except Exception as exc:
            self.relay.set_off()
            print(f"decision=DENY reason=sensor_read_error error={exc}")
            return False

        if voltage < self.config.valid_voltage_min or voltage > self.config.valid_voltage_max:
            self.relay.set_off()
            print(
                "decision=DENY reason=sensor_value_out_of_range "
                f"voltage={voltage:.3f}"
            )
            return False

        estimated_brac = self.estimate_brac(voltage)
        if estimated_brac is None:
            self.relay.set_off()
            print("decision=DENY reason=calibration_missing")
            return False

        if estimated_brac >= self.config.alcohol_threshold_brac:
            self.relay.set_off()
            print(
                "decision=DENY reason=alcohol_above_threshold "
                f"voltage={voltage:.3f} baseline={self._baseline_voltage:.3f} "
                f"estimated_brac={estimated_brac:.4f} threshold_brac={self.config.alcohol_threshold_brac:.4f}"
            )
            return False

        self.relay.set_on()
        print(
            "decision=ALLOW reason=below_threshold "
            f"voltage={voltage:.3f} baseline={self._baseline_voltage:.3f} "
            f"estimated_brac={estimated_brac:.4f} threshold_brac={self.config.alcohol_threshold_brac:.4f}"
        )
        return True


def calibrate_clean_air_baseline(
    reader: AnalogVoltageReader,
    output_file: str,
    samples: int,
    sample_interval_seconds: float,
    valid_voltage_min: float,
    valid_voltage_max: float,
) -> float:
    values: list[float] = []
    total_samples = max(5, samples)
    for index in range(total_samples):
        voltage = reader.read_voltage()
        if voltage < valid_voltage_min or voltage > valid_voltage_max:
            raise ValueError(f"Calibration sample out of range: {voltage:.3f}V")
        values.append(voltage)
        print(f"calibration_sample index={index + 1} voltage={voltage:.3f}")
        if index + 1 < total_samples:
            time.sleep(max(0.05, sample_interval_seconds))

    baseline = sum(values) / len(values)
    state_path = Path(output_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "clean_air_baseline_voltage": baseline,
        "sample_count": len(values),
        "created_at_epoch_s": time.time(),
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"calibration_complete baseline_voltage={baseline:.3f} file={output_file}")
    return baseline


def build_sensor(args: argparse.Namespace) -> AnalogVoltageReader:
    if args.mock_voltage is not None:
        return MockAnalogVoltageReader(fixed_voltage=args.mock_voltage)
    return ADS1115VoltageReader(channel=args.adc_channel, gain=args.adc_gain)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MQ-3 Gatekeeper primary runtime")
    parser.add_argument("--threshold-brac", type=float, default=0.02)
    parser.add_argument("--brac-per-volt-delta", type=float, default=0.04)
    parser.add_argument("--burn-in-hours", type=int, default=24)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--relay-pin", type=int, default=17)
    parser.add_argument("--active-high", action="store_true", default=True)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--adc-channel", type=int, default=0)
    parser.add_argument("--adc-gain", type=int, default=1)
    parser.add_argument("--mock-voltage", type=float)
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--burn-in-state-file", type=str, default="artifacts/mq3_burn_in_state.json")
    parser.add_argument("--calibration-state-file", type=str, default="artifacts/mq3_calibration_state.json")
    parser.add_argument("--calibrate-only", action="store_true", help="Capture clean-air baseline then exit")
    parser.add_argument("--calibration-samples", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    active_high = not args.active_low if args.active_low else args.active_high

    config = GatekeeperConfig(
        alcohol_threshold_brac=args.threshold_brac,
        brac_per_volt_delta=args.brac_per_volt_delta,
        burn_in_hours=args.burn_in_hours,
        sample_interval_seconds=args.sample_interval,
        burn_in_state_file=args.burn_in_state_file,
        calibration_state_file=args.calibration_state_file,
    )
    relay = RelayController(
        RelayConfig(relay_pin=args.relay_pin, active_high=active_high, dry_run=args.dry_run)
    )

    try:
        sensor = build_sensor(args)

        if args.calibrate_only:
            calibrate_clean_air_baseline(
                reader=sensor,
                output_file=config.calibration_state_file,
                samples=args.calibration_samples,
                sample_interval_seconds=config.sample_interval_seconds,
                valid_voltage_min=config.valid_voltage_min,
                valid_voltage_max=config.valid_voltage_max,
            )
            return

        gatekeeper = MQ3Gatekeeper(reader=sensor, relay=relay, config=config)

        remaining: Optional[int] = None if args.iterations <= 0 else args.iterations
        while remaining is None or remaining > 0:
            gatekeeper.evaluate_once()
            if remaining is not None:
                remaining -= 1
            time.sleep(config.sample_interval_seconds)
    finally:
        relay.cleanup()


if __name__ == "__main__":
    main()