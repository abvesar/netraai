import argparse
import json
import random
import sqlite3
import urllib.error
import urllib.request
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Protocol

from ai_tracking.safety_core import (
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
    def send_alert(self, payload: Dict[str, object]) -> bool:
        """Transmit a driver-risk alert via the configured channel."""

    def flush_pending(self) -> int:
        """Flush queued low-priority events when connectivity is restored."""


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


class KeyboardDriverSignalAdapter(FixedDriverSignalAdapter):
    """Windows keyboard demo adapter for live speed and look-away changes."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._keyboard = None
        try:
            import msvcrt

            self._keyboard = msvcrt
        except ImportError:
            pass

    def read(self, now_ms: int) -> DriverBehaviorSignal:
        if self._keyboard is not None:
            while self._keyboard.kbhit():
                key = self._keyboard.getwch()
                if key in {"\x00", "\xe0"}:
                    key = self._keyboard.getwch()
                if key == "H":
                    self.speed_kph += 5.0
                elif key == "P":
                    self.speed_kph = max(0.0, self.speed_kph - 5.0)
                elif key in {"K", "M"}:
                    self.distraction_score = 0.9
                elif key == "\x1b":
                    self.distraction_score = 0.1
            print(
                f"can_telemetry speed_kph={self.speed_kph:.0f} distraction_score={self.distraction_score:.2f}",
                flush=True,
            )
        return super().read(now_ms)


# ---------------------------------------------------------------------------
# Transmission adapters
# ---------------------------------------------------------------------------
class CloudTransmissionAdapter:
    def send_alert(self, payload: Dict[str, object]) -> bool:
        print(f"cloud_tx driver_id={payload.get('driver_id')} risk={payload.get('risk_level')} reasons={payload.get('reasons')}")
        return True

    def flush_pending(self) -> int:
        return 0


class SatelliteTransmissionAdapter:
    def send_alert(self, payload: Dict[str, object]) -> bool:
        risk_level = str(payload.get("risk_level", "NORMAL"))
        reasons = [str(reason) for reason in payload.get("reasons", [])]
        compact_packet = f"DRST|V1|R:{risk_level[:3]}|F:{reasons[0][:4] if reasons else 'none'}"
        print(f"[SATELLITE_TX] 4G/5G Signal Dead. Pushing compressed packet via satellite link: {compact_packet}", flush=True)
        return True

    def flush_pending(self) -> int:
        return 0


class StoreForwardQueue:
    """Persist low-priority events until cellular service is available again."""

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS store_forward_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    reasons TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def enqueue(self, payload: Dict[str, object]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO store_forward_queue (timestamp, risk_level, reasons, payload)
                VALUES (datetime('now'), ?, ?, ?)
                """,
                (
                    str(payload.get("risk_level", "NORMAL")),
                    json.dumps(payload.get("reasons", [])),
                    json.dumps(payload, separators=(",", ":")),
                ),
            )

    def drain(self) -> int:
        with sqlite3.connect(self.path) as connection:
            queued_ids = [row[0] for row in connection.execute("SELECT id FROM store_forward_queue")]
            if queued_ids:
                connection.executemany(
                    "DELETE FROM store_forward_queue WHERE id = ?",
                    ((item_id,) for item_id in queued_ids),
                )
        return len(queued_ids)


class HybridTransmissionAdapter:
    def __init__(
        self,
        cloud: CloudTransmissionAdapter,
        satellite: SatelliteTransmissionAdapter,
        queue: StoreForwardQueue,
        cellular_available: Callable[[], bool] | None = None,
    ) -> None:
        self.cloud = cloud
        self.satellite = satellite
        self.queue = queue
        self.cellular_available = cellular_available or (lambda: random.choice([True, False]))
        self.last_route: str | None = None

    def _report_route(self, route: str, reason: str) -> None:
        if route != self.last_route:
            previous = self.last_route or "startup"
            if route == "satellite":
                print("[NETWORK CRITICAL] 4G/5G connection lost. Routing shifted to Satellite Link.", flush=True)
            elif previous == "satellite":
                print("[NETWORK RESTORED] 4G/5G connection restored. Routing shifted to Cloud Link.", flush=True)
            print(f"hybrid_route from={previous} to={route} reason={reason}", flush=True)
            self.last_route = route

    def send_alert(self, payload: Dict[str, object]) -> bool:
        cellular_available = self.cellular_available()
        if cellular_available:
            self._report_route("cellular_4g_5g", "cellular_available")
            sent = self.cloud.send_alert(payload)
            self._flush_pending(cellular_available=True)
            return sent

        self._report_route("satellite", "cellular_unavailable")
        risk_level = str(payload.get("risk_level", "NORMAL"))
        reasons = payload.get("reasons", [])
        high_priority = risk_level == "HIGH" or any(
            reason in {"drowsiness_high", "distraction_high"} for reason in reasons
        )
        if high_priority:
            return self.satellite.send_alert(payload)

        self.queue.enqueue(payload)
        print(f"local_storage_cache risk={risk_level} reasons={reasons}")
        return False

    def flush_pending(self) -> int:
        return self._flush_pending(cellular_available=self.cellular_available())

    def _flush_pending(self, cellular_available: bool) -> int:
        if not cellular_available:
            self._report_route("satellite", "cellular_unavailable")
            return 0
        self._report_route("cellular_4g_5g", "cellular_available")
        drained = self.queue.drain()
        if drained:
            print(f"store_forward_sync count={drained}")
        return drained


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

        if assessment.reasons != ["behavior_normal"]:
            self.transmission.send_alert(payload)
        else:
            self.transmission.flush_pending()

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
    parser.add_argument("--cellular-state", choices=["auto", "up", "down"], default="auto")
    parser.add_argument("--keyboard-demo", action="store_true", help="Read speed/look-away changes from Windows arrow keys")
    parser.add_argument("--queue-db", default="local_audit_cache.db")
    parser.add_argument("--audit-log", default="artifacts/drishti_driver_monitoring.jsonl")
    return parser


def build_transmission_adapter(
    mode: str,
    queue_db: str = "local_audit_cache.db",
    cellular_state: str = "auto",
) -> TransmissionPort:
    cellular_available = None
    if cellular_state in {"up", "down"}:
        cellular_available = lambda: cellular_state == "up"
    else:
        cellular_available = _probe_cellular

    if mode == "cloud":
        return CloudTransmissionAdapter()
    if mode == "satellite":
        return SatelliteTransmissionAdapter()
    return HybridTransmissionAdapter(
        cloud=CloudTransmissionAdapter(),
        satellite=SatelliteTransmissionAdapter(),
        queue=StoreForwardQueue(queue_db),
        cellular_available=cellular_available,
    )


def _probe_cellular() -> bool:
    endpoint = "https://www.google.com/generate_204"
    try:
        with urllib.request.urlopen(endpoint, timeout=0.8):
            return True
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    args = build_parser().parse_args()

    signal_adapter = KeyboardDriverSignalAdapter if args.keyboard_demo else FixedDriverSignalAdapter
    signal_source = signal_adapter(
        driver_id=args.driver_id,
        vehicle_id=args.vehicle_id,
        drowsiness_score=args.drowsiness_score,
        distraction_score=args.distraction_score,
        yawning_score=args.yawning_score,
        phone_usage_score=args.phone_usage_score,
        speed_kph=args.speed_kph,
    )

    monitor = DriverBehaviorMonitor()
    transmission = build_transmission_adapter(
        args.transmission_mode,
        queue_db=args.queue_db,
        cellular_state=args.cellular_state,
    )
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
# from ai_tracking.driver_monitor import DrishtiAIDMS
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
