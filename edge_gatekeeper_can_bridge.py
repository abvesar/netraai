from __future__ import annotations

import argparse
import time

import can

from gatekeeper_primary import (
    ADS1115VoltageReader,
    GatekeeperConfig,
    MQ3Gatekeeper,
    MockAnalogVoltageReader,
    RelayConfig,
    RelayController,
)


ENGINE_START_REQUEST_ID = 0x100
HUB_OVERRIDE_ID = 0x101
ENGINE_STATUS_ID = 0x102


def build_sensor(mock_voltage: float | None, adc_channel: int, adc_gain: int):
    if mock_voltage is not None:
        return MockAnalogVoltageReader(fixed_voltage=mock_voltage)
    return ADS1115VoltageReader(channel=adc_channel, gain=adc_gain)


def send_override(bus: can.BusABC, allow: bool) -> None:
    payload = bytes([1 if allow else 0, 0, 0, 0, 0, 0, 0, 0])
    bus.send(can.Message(arbitration_id=HUB_OVERRIDE_ID, data=payload, is_extended_id=False))


def send_engine_status(bus: can.BusABC, allow: bool, node_id: int) -> None:
    status = 1 if allow else 3
    payload = bytes([status, node_id & 0xFF, 0, 0, 0, 0, 0, 0])
    bus.send(can.Message(arbitration_id=ENGINE_STATUS_ID, data=payload, is_extended_id=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edge Gatekeeper CAN bridge")
    parser.add_argument("--interface", default="virtual", help="python-can interface (virtual/socketcan)")
    parser.add_argument("--channel", default="vcan0", help="CAN channel")
    parser.add_argument("--node-id", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=0.5)
    parser.add_argument("--max-requests", type=int, default=0)

    parser.add_argument("--threshold-brac", type=float, default=0.02)
    parser.add_argument("--brac-per-volt-delta", type=float, default=0.04)
    parser.add_argument("--burn-in-hours", type=int, default=24)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--burn-in-state-file", default="artifacts/mq3_burn_in_state.json")
    parser.add_argument("--calibration-state-file", default="artifacts/mq3_calibration_state.json")

    parser.add_argument("--relay-pin", type=int, default=17)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=False)

    parser.add_argument("--adc-channel", type=int, default=0)
    parser.add_argument("--adc-gain", type=int, default=1)
    parser.add_argument("--mock-voltage", type=float)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    active_high = not args.active_low
    gatekeeper_config = GatekeeperConfig(
        alcohol_threshold_brac=args.threshold_brac,
        brac_per_volt_delta=args.brac_per_volt_delta,
        burn_in_hours=args.burn_in_hours,
        sample_interval_seconds=args.sample_interval,
        burn_in_state_file=args.burn_in_state_file,
        calibration_state_file=args.calibration_state_file,
    )

    sensor = build_sensor(args.mock_voltage, args.adc_channel, args.adc_gain)
    relay = RelayController(
        RelayConfig(relay_pin=args.relay_pin, active_high=active_high, dry_run=args.dry_run)
    )
    gatekeeper = MQ3Gatekeeper(reader=sensor, relay=relay, config=gatekeeper_config)

    bus = can.Bus(interface=args.interface, channel=args.channel, receive_own_messages=True)

    handled = 0
    try:
        print(
            "edge_bridge_ready "
            f"interface={args.interface} channel={args.channel} node_id={args.node_id}"
        )
        while args.max_requests <= 0 or handled < args.max_requests:
            msg = bus.recv(timeout=args.timeout)
            if msg is None:
                continue
            if msg.arbitration_id != ENGINE_START_REQUEST_ID:
                continue

            allow = gatekeeper.evaluate_once()
            send_override(bus=bus, allow=allow)
            send_engine_status(bus=bus, allow=allow, node_id=args.node_id)
            handled += 1
            print(f"edge_bridge_decision count={handled} allow={allow}")
            time.sleep(max(0.01, args.sample_interval))
        return 0
    finally:
        relay.cleanup()
        bus.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
