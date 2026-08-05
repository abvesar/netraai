from __future__ import annotations

import argparse
from datetime import datetime
import time

from hikvision_isapi import HikvisionIsapiClient, HikvisionIsapiConfig
from safety_core import SensorReading, SafetyGatekeeper, SafetyPolicyConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gatekeeper + Hikvision ISAPI simulation")
    parser.add_argument("--base-url", required=True, help="Camera base URL, e.g. http://192.168.1.10")
    parser.add_argument("--username", required=True, help="ISAPI username")
    parser.add_argument("--password", required=True, help="ISAPI password")
    parser.add_argument("--sensor-value", type=float, default=0.7, help="Mock alcohol reading")
    parser.add_argument("--facial-verified", action="store_true", help="Simulate successful facial verification")
    parser.add_argument("--threshold", type=float, default=0.5, help="Decision threshold")
    parser.add_argument("--snapshot-file", default="artifacts/frame.jpg", help="Path to save captured frame")
    parser.add_argument("--dry-run", action="store_true", help="Do not call camera APIs")
    parser.add_argument("--verify-tls", action="store_true", help="Verify camera TLS certificate")
    parser.add_argument("--sample-age-ms", type=int, default=0, help="Age of sample in ms for stale-data simulation")
    parser.add_argument("--uncalibrated", action="store_true", help="Mark sensor as not calibrated")
    parser.add_argument("--sensor-fault", action="store_true", help="Mark sensor health as failed")
    return parser


class NullOutput:
    def allow_access(self) -> None:
        print("ACCESS_ALLOWED")

    def deny_access(self) -> None:
        print("ACCESS_DENIED")


def main() -> int:
    args = build_parser().parse_args()

    now_ms = int(time.time() * 1000)
    reading = SensorReading(
        value=args.sensor_value,
        timestamp_ms=now_ms - max(0, args.sample_age_ms),
        facial_verified=args.facial_verified,
        sensor_ok=not args.sensor_fault,
        is_calibrated=not args.uncalibrated,
    )
    policy = SafetyGatekeeper(config=SafetyPolicyConfig(alcohol_threshold=args.threshold))
    result = policy.evaluate(reading=reading, now_ms=now_ms)

    output = NullOutput()
    if result.allowed:
        output.allow_access()
    else:
        output.deny_access()

    client = HikvisionIsapiClient(
        HikvisionIsapiConfig(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            dry_run=args.dry_run,
            verify_tls=args.verify_tls,
        )
    )

    frame_bytes = client.get_live_frame(output_file=args.snapshot_file)
    print(f"frame_bytes={len(frame_bytes)} saved={args.snapshot_file}")
    print(f"safety_decision={result.decision.value} reasons={','.join(result.reasons)}")

    if result.allowed:
        print("intervention=none")
        return 0

    client.trigger_alarm_output(output_id=1, active=True)
    message = f"[{datetime.utcnow().isoformat()}Z] Breath test failed. Stop vehicle and contact control room."
    client.speak_text(text=message, repeat=1)
    print("intervention=alarm_and_audio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
