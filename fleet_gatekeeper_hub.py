import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Protocol

from safety_core import (
    DriverBehaviorAssessment,
    DriverBehaviorMonitor,
    DriverBehaviorSignal,
)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
class DriverSignalPort(Protocol):
    def read(self, now_ms: int) -> DriverBehaviorSignal:
        """Return a real-time AI model input for the driver monitoring system."""


class TransmissionPort(Protocol):
    def send_alert(self, payload: Dict[str, object]) -> None:
        """Transmit a driver-risk alert via the configured channel."""


class AuditLogPort(Protocol):
    def write_event(self, event: Dict[str, object]) -> None:
        """Persist the AI-monitored driver event."""


# ---------------------------------------------------------------------------
# Configuration and signal adapters
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DrishtiHubConfig:
    cycle_seconds: float = 1.0
    max_cycles: int = 0
    transmission_mode: str = "cloud"


class FixedDriverSignalAdapter:
    def __init__(
        self,
        driver_id: str,
        vehicle_id: str,
        drowsiness_score: float,
        distraction_score: float,
        yawning_score: float = 0.0,
        phone_usage_score: float = 0.0,
        speed_kph: float = 0.0,
    ) -> None:
        self.driver_id = driver_id
        self.vehicle_id = vehicle_id
        self.drowsiness_score = drowsiness_score
        self.distraction_score = distraction_score
        self.yawning_score = yawning_score
        self.phone_usage_score = phone_usage_score
        self.speed_kph = speed_kph

    def read(self, now_ms: int) -> DriverBehaviorSignal:
        return DriverBehaviorSignal(
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            drowsiness_score=self.drowsiness_score,
            distraction_score=self.distraction_score,
            yawning_score=self.yawning_score,
            phone_usage_score=self.phone_usage_score,
            speed_kph=self.speed_kph,
            timestamp_ms=now_ms,
        )


# ---------------------------------------------------------------------------
# Transmission adapters
# ---------------------------------------------------------------------------
class CloudTransmissionAdapter:
    def send_alert(self, payload: Dict[str, object]) -> None:
        print(f"cloud_tx driver_id={payload.get('driver_id')} risk={payload.get('risk_level')} reasons={payload.get('reasons')}")


class SatelliteTransmissionAdapter:
    def send_alert(self, payload: Dict[str, object]) -> None:
        print(f"satellite_tx driver_id={payload.get('driver_id')} risk={payload.get('risk_level')} reasons={payload.get('reasons')}")


class HybridTransmissionAdapter:
    def __init__(self, cloud: CloudTransmissionAdapter, satellite: SatelliteTransmissionAdapter) -> None:
        self.cloud = cloud
        self.satellite = satellite

    def send_alert(self, payload: Dict[str, object]) -> None:
        self.cloud.send_alert(payload)
        self.satellite.send_alert(payload)


class JsonlAuditLogAdapter:
    def __init__(self, output_path: str) -> None:
        self.path = Path(output_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: Dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Monitoring service
# ---------------------------------------------------------------------------
class DrishtiDriverMonitoringService:
    """AI-first monitoring service that checks driver behavior and routes telemetry through cloud or satellite links."""

    def __init__(
        self,
        monitor: DriverBehaviorMonitor,
        signal_source: DriverSignalPort,
        transmission: TransmissionPort,
        audit: AuditLogPort,
    ) -> None:
        self.monitor = monitor
        self.signal_source = signal_source
        self.transmission = transmission
        self.audit = audit
        self.sequence_id = 0

    def evaluate_cycle(self) -> DriverBehaviorAssessment:
        now_ms = int(time.time() * 1000)
        signal = self.signal_source.read(now_ms=now_ms)
        assessment = self.monitor.evaluate(signal=signal, now_ms=now_ms)

        self.sequence_id += 1
        payload: Dict[str, object] = {
            "sequence_id": self.sequence_id,
            "timestamp_ms": now_ms,
            "driver_id": signal.driver_id,
            "vehicle_id": signal.vehicle_id,
            "risk_level": assessment.risk_level.value,
            "reasons": assessment.reasons,
            "confidence": assessment.confidence,
            "recommended_transmission": assessment.recommended_transmission,
            "drowsiness_score": signal.drowsiness_score,
            "distraction_score": signal.distraction_score,
            "speed_kph": signal.speed_kph,
        }

        if assessment.is_high_risk or assessment.recommended_transmission == "satellite":
            self.transmission.send_alert(payload)

        self.audit.write_event(payload)
        print(
            "ai_monitor "
            f"sequence_id={self.sequence_id} "
            f"driver_id={signal.driver_id} "
            f"risk={assessment.risk_level.value} "
            f"reasons={','.join(assessment.reasons)}"
        )
        return assessment


# ---------------------------------------------------------------------------
# CLI and composition
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DRISHTI AI driver monitoring hub")
    parser.add_argument("--driver-id", default="drv_001")
    parser.add_argument("--vehicle-id", default="veh_001")
    parser.add_argument("--drowsiness-score", type=float, default=0.82)
    parser.add_argument("--distraction-score", type=float, default=0.74)
    parser.add_argument("--yawning-score", type=float, default=0.2)
    parser.add_argument("--phone-usage-score", type=float, default=0.1)
    parser.add_argument("--speed-kph", type=float, default=82.0)
    parser.add_argument("--cycle-seconds", type=float, default=1.0)
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--transmission-mode", choices=["cloud", "satellite", "hybrid"], default="cloud")
    parser.add_argument("--audit-log", default="artifacts/drishti_driver_monitoring.jsonl")
    return parser


def build_transmission_adapter(mode: str) -> TransmissionPort:
    if mode == "cloud":
        return CloudTransmissionAdapter()
    if mode == "satellite":
        return SatelliteTransmissionAdapter()
    return HybridTransmissionAdapter(
        cloud=CloudTransmissionAdapter(),
        satellite=SatelliteTransmissionAdapter(),
    )


def main() -> int:
    args = build_parser().parse_args()

    signal_source = FixedDriverSignalAdapter(
        driver_id=args.driver_id,
        vehicle_id=args.vehicle_id,
        drowsiness_score=args.drowsiness_score,
        distraction_score=args.distraction_score,
        yawning_score=args.yawning_score,
        phone_usage_score=args.phone_usage_score,
        speed_kph=args.speed_kph,
    )

    monitor = DriverBehaviorMonitor()
    transmission = build_transmission_adapter(args.transmission_mode)
    audit = JsonlAuditLogAdapter(output_path=args.audit_log)

    service = DrishtiDriverMonitoringService(
        monitor=monitor,
        signal_source=signal_source,
        transmission=transmission,
        audit=audit,
    )

    config = DrishtiHubConfig(
        cycle_seconds=max(0.05, args.cycle_seconds),
        max_cycles=args.max_cycles,
        transmission_mode=args.transmission_mode,
    )
    remaining = None if config.max_cycles <= 0 else config.max_cycles

    while remaining is None or remaining > 0:
        service.evaluate_cycle()
        if remaining is not None:
            remaining -= 1
        if remaining is None or remaining > 0:
            time.sleep(config.cycle_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Reference sketch kept for design context only; not executed at import time.
# ---------------------------------------------------------------------------
# from driver_monitor import DrishtiAIDMS
# import cv2
#
# dms = DrishtiAIDMS()
# camera = cv2.VideoCapture(0)
#
# while True:
#     ret, frame = camera.read()
#     if not ret:
#         break
#
#     safety_signals = dms.process_frame(frame)
#
#     if safety_signals["drowsy"]:
#         trigger_hardware_buzzer()
#         send_high_risk_escalation(
#             reason="drowsiness_high",
#             mode="satellite" if network_low else "cloud",
#         )
#     elif safety_signals["distracted"]:
#         trigger_audio_intervention("Please keep your eyes on the road.")
