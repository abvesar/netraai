from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import can

from gatekeeper_primary import (
    GatekeeperConfig,
    MQ3Gatekeeper,
    MockAnalogVoltageReader,
    RelayConfig,
    RelayController,
    calibrate_clean_air_baseline,
)
from hikvision_isapi import HikvisionIsapiClient, HikvisionIsapiConfig


ENGINE_START_REQUEST_ID = 0x100
HUB_OVERRIDE_ID = 0x101
ENGINE_STATUS_ID = 0x102

STATUS_STOPPED = 0
STATUS_RUNNING = 1
STATUS_START_REQUESTED = 2
STATUS_START_BLOCKED = 3


@dataclass(frozen=True)
class ScenarioConfig:
    interface: str
    channel: str
    node_id: int
    requests: int
    request_interval_seconds: float
    status_interval_seconds: float
    loop_sleep_seconds: float


@dataclass(frozen=True)
class EdgeConfig:
    threshold_brac: float
    brac_per_volt_delta: float
    burn_in_hours: int
    burn_in_state_file: str
    calibration_state_file: str
    mock_voltage: float
    auto_calibrate: bool
    calibration_samples: int
    clean_air_voltage: float
    relay_pin: int
    active_low: bool
    dry_run: bool


@dataclass(frozen=True)
class HubConfig:
    enabled: bool
    base_url: str
    username: str
    password: str
    dry_run: bool
    verify_tls: bool
    snapshot_file: str
    alarm_output_id: int
    speak_repeat: int


class VirtualTruckNode:
    def __init__(self, bus: can.BusABC, config: ScenarioConfig) -> None:
        self.bus = bus
        self.config = config
        self.status = STATUS_STOPPED
        self.requests_sent = 0
        self.last_status_at = 0.0
        self.last_request_at = 0.0

    def tick(self, now: float) -> None:
        if now - self.last_status_at >= self.config.status_interval_seconds:
            self._send_engine_status(self.status)
            self.last_status_at = now

        if self.requests_sent < self.config.requests and now - self.last_request_at >= self.config.request_interval_seconds:
            self.status = STATUS_START_REQUESTED
            self._send_engine_status(self.status)
            self._send_start_request()
            self.last_request_at = now
            self.requests_sent += 1

    def handle_override(self, allow: bool) -> None:
        self.status = STATUS_RUNNING if allow else STATUS_START_BLOCKED
        self._send_engine_status(self.status)
        print(f"truck_rx override_allow={allow} status={self.status}")

    def _send_start_request(self) -> None:
        msg = can.Message(
            arbitration_id=ENGINE_START_REQUEST_ID,
            data=bytes([1, self.config.node_id & 0xFF, 0, 0, 0, 0, 0, 0]),
            is_extended_id=False,
        )
        self.bus.send(msg)
        print(f"truck_tx id=0x{ENGINE_START_REQUEST_ID:03X} start_request=1 data={msg.data.hex()}")

    def _send_engine_status(self, status: int) -> None:
        msg = can.Message(
            arbitration_id=ENGINE_STATUS_ID,
            data=bytes([status & 0xFF, self.config.node_id & 0xFF, 0, 0, 0, 0, 0, 0]),
            is_extended_id=False,
        )
        self.bus.send(msg)
        print(f"truck_tx id=0x{ENGINE_STATUS_ID:03X} status={status} data={msg.data.hex()}")


class EdgeGatekeeperNode:
    def __init__(self, bus: can.BusABC, gatekeeper: MQ3Gatekeeper, node_id: int) -> None:
        self.bus = bus
        self.gatekeeper = gatekeeper
        self.node_id = node_id
        self.decisions = 0

    def process_bus(self) -> None:
        while True:
            msg = self.bus.recv(timeout=0.0)
            if msg is None:
                return
            if msg.arbitration_id != ENGINE_START_REQUEST_ID:
                continue

            allow = self.gatekeeper.evaluate_once()
            self._send_override(allow=allow)
            self._send_engine_status(allow=allow)
            self.decisions += 1
            print(f"edge_tx decision_allow={allow} count={self.decisions}")

    def _send_override(self, allow: bool) -> None:
        payload = bytes([1 if allow else 0, 0, 0, 0, 0, 0, 0, 0])
        self.bus.send(can.Message(arbitration_id=HUB_OVERRIDE_ID, data=payload, is_extended_id=False))

    def _send_engine_status(self, allow: bool) -> None:
        status = STATUS_RUNNING if allow else STATUS_START_BLOCKED
        payload = bytes([status, self.node_id & 0xFF, 0, 0, 0, 0, 0, 0])
        self.bus.send(can.Message(arbitration_id=ENGINE_STATUS_ID, data=payload, is_extended_id=False))


class HubInterventionNode:
    def __init__(self, bus: can.BusABC, config: HubConfig) -> None:
        self.bus = bus
        self.config = config
        self._client = None
        self.override_events = 0

        if self.config.enabled:
            self._client = HikvisionIsapiClient(
                HikvisionIsapiConfig(
                    base_url=self.config.base_url,
                    username=self.config.username,
                    password=self.config.password,
                    dry_run=self.config.dry_run,
                    verify_tls=self.config.verify_tls,
                )
            )

    def process_bus(self) -> None:
        while True:
            msg = self.bus.recv(timeout=0.0)
            if msg is None:
                return
            if msg.arbitration_id != HUB_OVERRIDE_ID:
                continue

            allow = bool(msg.data[0])
            self.override_events += 1
            print(f"hub_rx override_allow={allow} count={self.override_events}")

            if allow:
                continue

            if self._client is None:
                print("hub_intervention skipped=true reason=hub_disabled")
                continue

            frame = self._client.get_live_frame(output_file=self.config.snapshot_file)
            self._client.trigger_alarm_output(output_id=self.config.alarm_output_id, active=True)
            self._client.speak_text(
                text="Safety violation detected. Vehicle start is blocked.",
                repeat=self.config.speak_repeat,
            )
            print(f"hub_intervention action=alarm_audio_snapshot bytes={len(frame)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Integrated scenario runner: truck + edge gatekeeper + hub")

    parser.add_argument("--interface", default="virtual")
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--node-id", type=int, default=1)
    parser.add_argument("--requests", type=int, default=3)
    parser.add_argument("--request-interval", type=float, default=0.5)
    parser.add_argument("--status-interval", type=float, default=0.25)
    parser.add_argument("--loop-sleep", type=float, default=0.02)

    parser.add_argument("--threshold-brac", type=float, default=0.02)
    parser.add_argument("--brac-per-volt-delta", type=float, default=0.04)
    parser.add_argument("--burn-in-hours", type=int, default=0)
    parser.add_argument("--burn-in-state-file", default="artifacts/mq3_burn_in_state.json")
    parser.add_argument("--calibration-state-file", default="artifacts/mq3_calibration_state_runner.json")
    parser.add_argument("--mock-voltage", type=float, default=1.60)
    parser.add_argument("--auto-calibrate", action="store_true", default=True)
    parser.add_argument("--calibration-samples", type=int, default=5)
    parser.add_argument("--clean-air-voltage", type=float, default=1.00)
    parser.add_argument("--relay-pin", type=int, default=17)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)

    parser.add_argument("--hub-enabled", action="store_true", default=True)
    parser.add_argument("--hub-base-url", default="http://127.0.0.1")
    parser.add_argument("--hub-username", default="admin")
    parser.add_argument("--hub-password", default="admin")
    parser.add_argument("--hub-dry-run", action="store_true", default=True)
    parser.add_argument("--hub-verify-tls", action="store_true")
    parser.add_argument("--snapshot-file", default="artifacts/intervention_frame_runner.jpg")
    parser.add_argument("--alarm-output-id", type=int, default=1)
    parser.add_argument("--speak-repeat", type=int, default=1)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    scenario = ScenarioConfig(
        interface=args.interface,
        channel=args.channel,
        node_id=args.node_id,
        requests=max(1, args.requests),
        request_interval_seconds=max(0.1, args.request_interval),
        status_interval_seconds=max(0.1, args.status_interval),
        loop_sleep_seconds=max(0.005, args.loop_sleep),
    )

    edge_cfg = EdgeConfig(
        threshold_brac=args.threshold_brac,
        brac_per_volt_delta=args.brac_per_volt_delta,
        burn_in_hours=max(0, args.burn_in_hours),
        burn_in_state_file=args.burn_in_state_file,
        calibration_state_file=args.calibration_state_file,
        mock_voltage=args.mock_voltage,
        auto_calibrate=args.auto_calibrate,
        calibration_samples=max(5, args.calibration_samples),
        clean_air_voltage=args.clean_air_voltage,
        relay_pin=args.relay_pin,
        active_low=args.active_low,
        dry_run=args.dry_run,
    )

    hub_cfg = HubConfig(
        enabled=args.hub_enabled,
        base_url=args.hub_base_url,
        username=args.hub_username,
        password=args.hub_password,
        dry_run=args.hub_dry_run,
        verify_tls=args.hub_verify_tls,
        snapshot_file=args.snapshot_file,
        alarm_output_id=args.alarm_output_id,
        speak_repeat=max(1, args.speak_repeat),
    )

    if edge_cfg.auto_calibrate:
        calibrator = MockAnalogVoltageReader(fixed_voltage=edge_cfg.clean_air_voltage)
        calibrate_clean_air_baseline(
            reader=calibrator,
            output_file=edge_cfg.calibration_state_file,
            samples=edge_cfg.calibration_samples,
            sample_interval_seconds=0.02,
            valid_voltage_min=0.0,
            valid_voltage_max=5.0,
        )
    elif not Path(edge_cfg.calibration_state_file).exists():
        print("error=calibration_missing auto_calibrate=false")
        return 2

    edge_sensor = MockAnalogVoltageReader(fixed_voltage=edge_cfg.mock_voltage)
    edge_relay = RelayController(
        RelayConfig(relay_pin=edge_cfg.relay_pin, active_high=not edge_cfg.active_low, dry_run=edge_cfg.dry_run)
    )
    gatekeeper = MQ3Gatekeeper(
        reader=edge_sensor,
        relay=edge_relay,
        config=GatekeeperConfig(
            alcohol_threshold_brac=edge_cfg.threshold_brac,
            brac_per_volt_delta=edge_cfg.brac_per_volt_delta,
            burn_in_hours=edge_cfg.burn_in_hours,
            burn_in_state_file=edge_cfg.burn_in_state_file,
            calibration_state_file=edge_cfg.calibration_state_file,
        ),
    )

    truck_bus = can.Bus(interface=scenario.interface, channel=scenario.channel, receive_own_messages=True)
    edge_bus = can.Bus(interface=scenario.interface, channel=scenario.channel, receive_own_messages=True)
    hub_bus = can.Bus(interface=scenario.interface, channel=scenario.channel, receive_own_messages=True)

    truck = VirtualTruckNode(truck_bus, scenario)
    edge = EdgeGatekeeperNode(edge_bus, gatekeeper, scenario.node_id)
    hub = HubInterventionNode(hub_bus, hub_cfg)

    try:
        print(
            "scenario_start "
            f"interface={scenario.interface} channel={scenario.channel} requests={scenario.requests}"
        )
        timeout_at = time.time() + max(5.0, scenario.requests * scenario.request_interval_seconds * 8.0)
        while time.time() < timeout_at:
            now = time.time()
            truck.tick(now)
            edge.process_bus()
            hub.process_bus()

            if edge.decisions >= scenario.requests and hub.override_events >= scenario.requests:
                break

            time.sleep(scenario.loop_sleep_seconds)

        print(
            "scenario_done "
            f"requests_sent={truck.requests_sent} edge_decisions={edge.decisions} hub_overrides={hub.override_events}"
        )
        if edge.decisions < scenario.requests:
            return 1
        return 0
    finally:
        edge_relay.cleanup()
        truck_bus.shutdown()
        edge_bus.shutdown()
        hub_bus.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
