from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Optional

try:
    import can
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "python-can is required. Install with: pip install python-can"
    ) from exc

from safety_core import SensorReading, SafetyDecisionResult, SafetyGatekeeper, SafetyPolicyConfig
from hikvision_isapi import HikvisionIsapiClient, HikvisionIsapiConfig


ENGINE_START_REQUEST_ID = 0x100
HUB_OVERRIDE_ID = 0x101
ENGINE_STATUS_ID = 0x102


class EngineStatus(IntEnum):
    STOPPED = 0
    RUNNING = 1
    START_REQUESTED = 2
    START_BLOCKED = 3


@dataclass(frozen=True)
class SimulationConfig:
    channel: str = "vcan0"
    interface: str = "virtual"
    threshold: float = 0.5
    sensor_value: float = 0.42
    facial_verified: bool = True
    timeout_seconds: float = 0.5
    max_sample_age_ms: int = 5000
    node_id: int = 1
    request_interval_seconds: float = 2.0
    status_interval_seconds: float = 1.0
    max_messages: int = 30


@dataclass(frozen=True)
class CameraInterventionConfig:
    enabled: bool = False
    base_url: str = ""
    username: str = ""
    password: str = ""
    dry_run: bool = True
    verify_tls: bool = False
    snapshot_file: str = "artifacts/frame.jpg"
    alarm_output_id: int = 1
    speak_repeat: int = 1
    intervention_message: str = "Breath test failed. Stop vehicle and contact control room."


class CanDecisionOutput:
    def __init__(self, bus: can.BusABC) -> None:
        self.bus = bus

    def allow_access(self) -> None:
        self._send_override(allow=True)

    def deny_access(self) -> None:
        self._send_override(allow=False)

    def _send_override(self, allow: bool) -> None:
        payload = bytes([1 if allow else 0, 0, 0, 0, 0, 0, 0, 0])
        message = can.Message(
            arbitration_id=HUB_OVERRIDE_ID,
            data=payload,
            is_extended_id=False,
        )
        self.bus.send(message)


class ActiveInterventionController:
    def __init__(self, config: CameraInterventionConfig) -> None:
        self.config = config
        self._client: Optional[HikvisionIsapiClient] = None

        if not self.config.enabled:
            return

        self._client = HikvisionIsapiClient(
            HikvisionIsapiConfig(
                base_url=self.config.base_url,
                username=self.config.username,
                password=self.config.password,
                dry_run=self.config.dry_run,
                verify_tls=self.config.verify_tls,
            )
        )

    def capture_frame_for_verification(self) -> bool:
        if self._client is None:
            print("camera_capture skipped=true reason=camera_disabled")
            return True

        try:
            frame_bytes = self._client.get_live_frame(output_file=self.config.snapshot_file)
            print(
                "camera_capture skipped=false "
                f"bytes={len(frame_bytes)} saved={self.config.snapshot_file}"
            )
            return True
        except Exception as exc:
            print(f"camera_capture failed=true error={exc}")
            return False

    def trigger_deny_intervention(self, reasons: str) -> None:
        if self._client is None:
            print("intervention skipped=true reason=camera_disabled")
            return

        timestamp = datetime.utcnow().isoformat() + "Z"
        message = f"[{timestamp}] {self.config.intervention_message} Reasons: {reasons}"

        self._client.trigger_alarm_output(output_id=self.config.alarm_output_id, active=True)
        self._client.speak_text(text=message, repeat=self.config.speak_repeat)
        print("intervention action=alarm_and_audio")


def send_engine_status(bus: can.BusABC, status: EngineStatus, node_id: int) -> None:
    payload = bytes([int(status), node_id & 0xFF, 0, 0, 0, 0, 0, 0])
    msg = can.Message(
        arbitration_id=ENGINE_STATUS_ID,
        data=payload,
        is_extended_id=False,
    )
    bus.send(msg)


def make_bus(config: SimulationConfig) -> can.BusABC:
    return can.Bus(interface=config.interface, channel=config.channel, receive_own_messages=True)


def send_engine_start_request(bus: can.BusABC) -> None:
    msg = can.Message(
        arbitration_id=ENGINE_START_REQUEST_ID,
        data=bytes([1, 0, 0, 0, 0, 0, 0, 0]),
        is_extended_id=False,
    )
    bus.send(msg)


def wait_for_engine_start_request(bus: can.BusABC, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    request: Optional[can.Message] = None
    while time.time() < deadline:
        msg = bus.recv(timeout=0.1)
        if msg is None:
            continue
        if msg.arbitration_id == ENGINE_START_REQUEST_ID:
            request = msg
            break

    return request is not None


def evaluate_request(
    bus: can.BusABC,
    config: SimulationConfig,
    policy: SafetyGatekeeper,
    output: CanDecisionOutput,
    intervention: ActiveInterventionController,
) -> SafetyDecisionResult:
    frame_ok = intervention.capture_frame_for_verification()
    now_ms = int(time.time() * 1000)
    reading = SensorReading(
        value=config.sensor_value,
        timestamp_ms=now_ms,
        facial_verified=config.facial_verified and frame_ok,
        sensor_ok=True,
        is_calibrated=True,
    )
    decision = policy.evaluate(reading=reading, now_ms=now_ms)

    if decision.allowed:
        output.allow_access()
        send_engine_status(bus, EngineStatus.RUNNING, config.node_id)
    else:
        output.deny_access()
        send_engine_status(bus, EngineStatus.START_BLOCKED, config.node_id)
        intervention.trigger_deny_intervention(reasons=",".join(decision.reasons))

    return decision


def read_override(bus: can.BusABC, timeout_seconds: float = 1.0) -> Optional[bool]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        msg = bus.recv(timeout=0.2)
        if msg is None:
            continue
        if msg.arbitration_id != HUB_OVERRIDE_ID:
            continue
        return bool(msg.data[0])
    return None


def run_hub(config: SimulationConfig, camera_config: CameraInterventionConfig) -> int:
    bus = make_bus(config)
    policy = SafetyGatekeeper(
        config=SafetyPolicyConfig(
            alcohol_threshold=config.threshold,
            max_sample_age_ms=config.max_sample_age_ms,
        )
    )
    output = CanDecisionOutput(bus=bus)
    intervention = ActiveInterventionController(config=camera_config)
    handled = 0

    try:
        print(
            "hub_ready "
            f"interface={config.interface} channel={config.channel} threshold={config.threshold}"
        )
        while handled < config.max_messages:
            msg = bus.recv(timeout=config.timeout_seconds)
            if msg is None:
                continue
            if msg.arbitration_id != ENGINE_START_REQUEST_ID:
                continue

            decision = evaluate_request(
                bus=bus,
                config=config,
                policy=policy,
                output=output,
                intervention=intervention,
            )

            handled += 1
            print(
                "hub_decision "
                f"count={handled} "
                f"decision={decision.decision.value} "
                f"reasons={','.join(decision.reasons)}"
            )
        return 0
    finally:
        bus.shutdown()


def run_vehicle(config: SimulationConfig) -> int:
    bus = make_bus(config)
    sent = 0
    last_request_at = 0.0
    last_status_at = 0.0
    status = EngineStatus.STOPPED

    try:
        print(
            "vehicle_ready "
            f"interface={config.interface} channel={config.channel} node_id={config.node_id}"
        )
        while sent < config.max_messages:
            now = time.time()

            if now - last_status_at >= config.status_interval_seconds:
                send_engine_status(bus, status, config.node_id)
                print(f"vehicle_status status={status.name}")
                last_status_at = now

            if now - last_request_at >= config.request_interval_seconds:
                status = EngineStatus.START_REQUESTED
                send_engine_status(bus, status, config.node_id)
                send_engine_start_request(bus)
                print("vehicle_request engine_start=1")
                last_request_at = now
                sent += 1

            override = read_override(bus, timeout_seconds=0.1)
            if override is not None:
                status = EngineStatus.RUNNING if override else EngineStatus.START_BLOCKED
                send_engine_status(bus, status, config.node_id)
                print(f"vehicle_override allow={override} status={status.name}")

        return 0
    finally:
        bus.shutdown()


def run_monitor(config: SimulationConfig) -> int:
    bus = make_bus(config)
    seen = 0
    try:
        print(f"monitor_ready interface={config.interface} channel={config.channel}")
        while seen < config.max_messages:
            msg = bus.recv(timeout=config.timeout_seconds)
            if msg is None:
                continue
            seen += 1
            data_hex = msg.data.hex()
            print(f"frame id=0x{msg.arbitration_id:03X} dlc={msg.dlc} data={data_hex}")
        return 0
    finally:
        bus.shutdown()


def run_demo(config: SimulationConfig, camera_config: CameraInterventionConfig) -> int:
    bus = make_bus(config)
    policy = SafetyGatekeeper(
        config=SafetyPolicyConfig(
            alcohol_threshold=config.threshold,
            max_sample_age_ms=config.max_sample_age_ms,
        )
    )
    output = CanDecisionOutput(bus=bus)
    intervention = ActiveInterventionController(config=camera_config)
    try:
        send_engine_status(bus, EngineStatus.STOPPED, config.node_id)
        send_engine_start_request(bus)
        if not wait_for_engine_start_request(bus, timeout_seconds=config.timeout_seconds):
            print("No engine-start request handled")
            return 1

        result = evaluate_request(
            bus=bus,
            config=config,
            policy=policy,
            output=output,
            intervention=intervention,
        )

        override = read_override(bus)
        if override is True:
            send_engine_status(bus, EngineStatus.RUNNING, config.node_id)
        else:
            send_engine_status(bus, EngineStatus.START_BLOCKED, config.node_id)

        print(
            "request=ENGINE_START "
            f"decision={result.decision.value} "
            f"override={override} "
            f"reasons={','.join(result.reasons)}"
        )
        return 0
    finally:
        bus.shutdown()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Virtual CAN gatekeeper simulation")
    parser.add_argument(
        "--mode",
        default="demo",
        choices=["demo", "hub", "vehicle", "monitor"],
        help="Run mode: demo single-process flow, hub decision node, vehicle node, or monitor",
    )
    parser.add_argument("--interface", default="virtual", help="python-can interface (virtual or socketcan)")
    parser.add_argument("--channel", default="vcan0", help="CAN channel (vcan0 for socketcan)")
    parser.add_argument("--threshold", type=float, default=0.5, help="Decision threshold")
    parser.add_argument("--sensor-value", type=float, default=0.42, help="Mock alcohol value")
    parser.add_argument("--facial-verified", action="store_true", default=True, help="Simulate successful facial verification")
    parser.add_argument("--facial-unverified", action="store_true", help="Force facial verification failure")
    parser.add_argument("--max-sample-age-ms", type=int, default=5000, help="Maximum valid sensor sample age")
    parser.add_argument("--node-id", type=int, default=1, help="Vehicle node identifier (0-255)")
    parser.add_argument("--request-interval", type=float, default=2.0, help="Vehicle start request interval")
    parser.add_argument("--status-interval", type=float, default=1.0, help="Vehicle status broadcast interval")
    parser.add_argument("--max-messages", type=int, default=30, help="Maximum loop events before exit")
    parser.add_argument("--camera-enabled", action="store_true", help="Enable Hikvision/Prama ISAPI actions")
    parser.add_argument("--camera-base-url", default="", help="Camera base URL, e.g. http://192.168.1.10")
    parser.add_argument("--camera-username", default="", help="Camera username")
    parser.add_argument("--camera-password", default="", help="Camera password")
    parser.add_argument("--camera-dry-run", action="store_true", help="Do not call live camera endpoints")
    parser.add_argument("--camera-verify-tls", action="store_true", help="Verify camera TLS cert")
    parser.add_argument("--snapshot-file", default="artifacts/frame.jpg", help="Path to save captured frame")
    parser.add_argument("--alarm-output-id", type=int, default=1, help="ISAPI alarm output ID")
    parser.add_argument("--speak-repeat", type=int, default=1, help="Audio repeat count")
    parser.add_argument(
        "--intervention-message",
        default="Breath test failed. Stop vehicle and contact control room.",
        help="Audio intervention message",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    config = SimulationConfig(
        interface=args.interface,
        channel=args.channel,
        threshold=args.threshold,
        sensor_value=args.sensor_value,
        facial_verified=(False if args.facial_unverified else args.facial_verified),
        max_sample_age_ms=args.max_sample_age_ms,
        node_id=args.node_id,
        request_interval_seconds=args.request_interval,
        status_interval_seconds=args.status_interval,
        max_messages=max(1, args.max_messages),
    )

    camera_enabled = args.camera_enabled
    if camera_enabled and (not args.camera_base_url or not args.camera_username or not args.camera_password):
        print("camera_enabled requires --camera-base-url, --camera-username, --camera-password")
        return 2

    camera_config = CameraInterventionConfig(
        enabled=camera_enabled,
        base_url=args.camera_base_url,
        username=args.camera_username,
        password=args.camera_password,
        dry_run=args.camera_dry_run,
        verify_tls=args.camera_verify_tls,
        snapshot_file=args.snapshot_file,
        alarm_output_id=args.alarm_output_id,
        speak_repeat=max(1, args.speak_repeat),
        intervention_message=args.intervention_message,
    )

    if args.mode == "demo":
        return run_demo(config, camera_config)
    if args.mode == "hub":
        return run_hub(config, camera_config)
    if args.mode == "vehicle":
        return run_vehicle(config)
    return run_monitor(config)


if __name__ == "__main__":
    sys.exit(main())
