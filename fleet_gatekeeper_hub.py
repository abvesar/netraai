from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from hikvision_isapi import HikvisionIsapiClient, HikvisionIsapiConfig
from safety_core import SafetyDecisionResult, SafetyGatekeeper, SafetyPolicyConfig, SensorReading


ENGINE_STATUS_ID = 0x102
HUB_OVERRIDE_ID = 0x101


class AlcoholSensorPort(Protocol):
    def read(self, now_ms: int) -> SensorReading:
        """Return normalized alcohol-domain reading in [0.0, 1.0]."""


class VehicleNetworkPort(Protocol):
    def publish_override(self, allow: bool) -> None:
        """Publish ignition override decision to in-vehicle network."""

    def publish_engine_status(self, status_code: int) -> None:
        """Publish engine state used by downstream telematics."""


class ImmobilizerPort(Protocol):
    def allow_start(self) -> None:
        """Release starter/ignition relay."""

    def deny_start(self) -> None:
        """Keep starter/ignition relay disabled."""


class CameraInterventionPort(Protocol):
    def capture_for_verification(self) -> bool:
        """Capture frame for facial verification workflow."""

    def trigger_active_intervention(self, reason_text: str) -> None:
        """Speak warning and/or trigger alarm output."""


class AuditLogPort(Protocol):
    def write_event(self, event: dict[str, object]) -> None:
        """Write immutable decision event for safety audit."""


@dataclass(frozen=True)
class HubConfig:
    cycle_seconds: float = 1.0
    max_cycles: int = 0


class FixedSensorAdapter:
    def __init__(self, value: float, facial_verified: bool = True, sensor_ok: bool = True, calibrated: bool = True) -> None:
        self.value = value
        self.facial_verified = facial_verified
        self.sensor_ok = sensor_ok
        self.calibrated = calibrated

    def read(self, now_ms: int) -> SensorReading:
        return SensorReading(
            value=self.value,
            timestamp_ms=now_ms,
            facial_verified=self.facial_verified,
            sensor_ok=self.sensor_ok,
            is_calibrated=self.calibrated,
        )


class StdoutVehicleNetworkAdapter:
    def publish_override(self, allow: bool) -> None:
        state = 1 if allow else 0
        print(f"can_tx id=0x{HUB_OVERRIDE_ID:03X} data={state:02x}00000000000000")

    def publish_engine_status(self, status_code: int) -> None:
        print(f"can_tx id=0x{ENGINE_STATUS_ID:03X} data={status_code:02x}01000000000000")


class PythonCanVehicleNetworkAdapter:
    def __init__(self, interface: str, channel: str) -> None:
        try:
            import can
        except Exception as exc:
            raise RuntimeError("python-can is required. Install with: pip install python-can") from exc

        self._can = can
        self._bus = can.Bus(interface=interface, channel=channel, receive_own_messages=True)

    def publish_override(self, allow: bool) -> None:
        payload = bytes([1 if allow else 0, 0, 0, 0, 0, 0, 0, 0])
        self._bus.send(self._can.Message(arbitration_id=HUB_OVERRIDE_ID, data=payload, is_extended_id=False))

    def publish_engine_status(self, status_code: int) -> None:
        payload = bytes([status_code & 0xFF, 1, 0, 0, 0, 0, 0, 0])
        self._bus.send(self._can.Message(arbitration_id=ENGINE_STATUS_ID, data=payload, is_extended_id=False))


class StdoutImmobilizerAdapter:
    def allow_start(self) -> None:
        print("immobilizer state=ALLOW")

    def deny_start(self) -> None:
        print("immobilizer state=DENY")


class HikvisionInterventionAdapter:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        dry_run: bool,
        verify_tls: bool,
        snapshot_file: str,
        alarm_output_id: int,
        repeat: int,
    ) -> None:
        self.snapshot_file = snapshot_file
        self.alarm_output_id = alarm_output_id
        self.repeat = repeat
        self._client = HikvisionIsapiClient(
            HikvisionIsapiConfig(
                base_url=base_url,
                username=username,
                password=password,
                dry_run=dry_run,
                verify_tls=verify_tls,
            )
        )

    def capture_for_verification(self) -> bool:
        try:
            frame = self._client.get_live_frame(output_file=self.snapshot_file)
            print(f"camera_capture ok=true bytes={len(frame)} saved={self.snapshot_file}")
            return True
        except Exception as exc:
            print(f"camera_capture ok=false error={exc}")
            return False

    def trigger_active_intervention(self, reason_text: str) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        message = f"[{ts}] Breath test failed. Vehicle start blocked. Reasons: {reason_text}"
        self._client.trigger_alarm_output(output_id=self.alarm_output_id, active=True)
        self._client.speak_text(text=message, repeat=self.repeat)
        print("camera_intervention action=alarm_and_audio")


class NullCameraInterventionAdapter:
    def capture_for_verification(self) -> bool:
        print("camera_capture skipped=true")
        return True

    def trigger_active_intervention(self, reason_text: str) -> None:
        print(f"camera_intervention skipped=true reasons={reason_text}")


class JsonlAuditLogAdapter:
    def __init__(self, output_path: str) -> None:
        self.path = Path(output_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")


class FleetGatekeeperHubService:
    """Application-layer service with fail-safe actuation and adapter-agnostic ports."""

    def __init__(
        self,
        policy: SafetyGatekeeper,
        sensor: AlcoholSensorPort,
        vehicle_network: VehicleNetworkPort,
        immobilizer: ImmobilizerPort,
        camera: CameraInterventionPort,
        audit: AuditLogPort,
    ) -> None:
        self.policy = policy
        self.sensor = sensor
        self.vehicle_network = vehicle_network
        self.immobilizer = immobilizer
        self.camera = camera
        self.audit = audit
        self.sequence_id = 0

    def evaluate_start_request(self) -> SafetyDecisionResult:
        now_ms = int(time.time() * 1000)

        # Fail-safe default for each request cycle.
        self.immobilizer.deny_start()

        reading = self.sensor.read(now_ms=now_ms)
        frame_ok = self.camera.capture_for_verification()

        reading_with_face = SensorReading(
            value=reading.value,
            timestamp_ms=reading.timestamp_ms,
            facial_verified=reading.facial_verified and frame_ok,
            sensor_ok=reading.sensor_ok,
            is_calibrated=reading.is_calibrated,
        )

        result = self.policy.evaluate(reading=reading_with_face, now_ms=now_ms)

        if result.allowed:
            self.immobilizer.allow_start()
            self.vehicle_network.publish_override(allow=True)
            self.vehicle_network.publish_engine_status(status_code=1)
        else:
            self.immobilizer.deny_start()
            self.vehicle_network.publish_override(allow=False)
            self.vehicle_network.publish_engine_status(status_code=3)
            self.camera.trigger_active_intervention(reason_text=",".join(result.reasons))

        self.sequence_id += 1
        self.audit.write_event(
            {
                "sequence_id": self.sequence_id,
                "timestamp_ms": now_ms,
                "decision": result.decision.value,
                "reasons": result.reasons,
                "sensor_value": reading_with_face.value,
                "facial_verified": reading_with_face.facial_verified,
                "sensor_ok": reading_with_face.sensor_ok,
                "is_calibrated": reading_with_face.is_calibrated,
            }
        )

        print(
            "hub_decision "
            f"sequence_id={self.sequence_id} "
            f"decision={result.decision.value} "
            f"reasons={','.join(result.reasons)}"
        )
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fleet Gatekeeper Hub (AUTOSAR-style abstraction)")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--sensor-value", type=float, default=0.42)
    parser.add_argument("--facial-unverified", action="store_true")
    parser.add_argument("--sensor-fault", action="store_true")
    parser.add_argument("--uncalibrated", action="store_true")
    parser.add_argument("--max-sample-age-ms", type=int, default=5000)

    parser.add_argument("--cycle-seconds", type=float, default=1.0)
    parser.add_argument("--max-cycles", type=int, default=1)

    parser.add_argument("--can-interface", default="")
    parser.add_argument("--can-channel", default="vcan0")

    parser.add_argument("--camera-enabled", action="store_true")
    parser.add_argument("--camera-base-url", default="")
    parser.add_argument("--camera-username", default="")
    parser.add_argument("--camera-password", default="")
    parser.add_argument("--camera-dry-run", action="store_true")
    parser.add_argument("--camera-verify-tls", action="store_true")
    parser.add_argument("--snapshot-file", default="artifacts/frame.jpg")
    parser.add_argument("--alarm-output-id", type=int, default=1)
    parser.add_argument("--speak-repeat", type=int, default=1)

    parser.add_argument("--audit-log", default="artifacts/gatekeeper_events.jsonl")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    policy = SafetyGatekeeper(
        config=SafetyPolicyConfig(
            alcohol_threshold=args.threshold,
            max_sample_age_ms=args.max_sample_age_ms,
        )
    )

    sensor = FixedSensorAdapter(
        value=args.sensor_value,
        facial_verified=not args.facial_unverified,
        sensor_ok=not args.sensor_fault,
        calibrated=not args.uncalibrated,
    )

    if args.can_interface:
        vehicle_network: VehicleNetworkPort = PythonCanVehicleNetworkAdapter(
            interface=args.can_interface,
            channel=args.can_channel,
        )
    else:
        vehicle_network = StdoutVehicleNetworkAdapter()

    immobilizer = StdoutImmobilizerAdapter()

    if args.camera_enabled:
        if not args.camera_base_url or not args.camera_username or not args.camera_password:
            print("camera_enabled requires --camera-base-url, --camera-username, --camera-password")
            return 2
        camera: CameraInterventionPort = HikvisionInterventionAdapter(
            base_url=args.camera_base_url,
            username=args.camera_username,
            password=args.camera_password,
            dry_run=args.camera_dry_run,
            verify_tls=args.camera_verify_tls,
            snapshot_file=args.snapshot_file,
            alarm_output_id=args.alarm_output_id,
            repeat=max(1, args.speak_repeat),
        )
    else:
        camera = NullCameraInterventionAdapter()

    audit = JsonlAuditLogAdapter(output_path=args.audit_log)

    service = FleetGatekeeperHubService(
        policy=policy,
        sensor=sensor,
        vehicle_network=vehicle_network,
        immobilizer=immobilizer,
        camera=camera,
        audit=audit,
    )

    config = HubConfig(cycle_seconds=max(0.05, args.cycle_seconds), max_cycles=args.max_cycles)
    remaining = None if config.max_cycles <= 0 else config.max_cycles

    while remaining is None or remaining > 0:
        service.evaluate_start_request()
        if remaining is not None:
            remaining -= 1
        if remaining is None or remaining > 0:
            time.sleep(config.cycle_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
