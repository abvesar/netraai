import unittest

from safety_core import (
    DriverBehaviorSignal,
    DriverBehaviorMonitor,
    DriverRiskLevel,
    SafetyDecision,
    SafetyGatekeeper,
    SafetyPolicyConfig,
    SensorReading,
)
from driver_monitor_dashboard import build_capture_candidates


class SafetyCoreTests(unittest.TestCase):
    def test_allow_when_all_checks_pass(self) -> None:
        policy = SafetyGatekeeper(SafetyPolicyConfig(alcohol_threshold=0.5))
        reading = SensorReading(
            value=0.3,
            timestamp_ms=1000,
            facial_verified=True,
            sensor_ok=True,
            is_calibrated=True,
        )
        result = policy.evaluate(reading=reading, now_ms=1000)
        self.assertEqual(result.decision, SafetyDecision.ALLOW)
        self.assertEqual(result.reasons, ["all_checks_passed"])

    def test_deny_when_facial_or_alcohol_fails(self) -> None:
        policy = SafetyGatekeeper(SafetyPolicyConfig(alcohol_threshold=0.5))
        reading = SensorReading(
            value=0.8,
            timestamp_ms=1000,
            facial_verified=False,
            sensor_ok=True,
            is_calibrated=True,
        )
        result = policy.evaluate(reading=reading, now_ms=1000)
        self.assertEqual(result.decision, SafetyDecision.DENY)
        self.assertIn("facial_not_verified", result.reasons)
        self.assertIn("alcohol_above_threshold", result.reasons)

    def test_ai_monitor_flags_drowsiness_and_distraction(self) -> None:
        monitor = DriverBehaviorMonitor()
        signal = DriverBehaviorSignal(
            driver_id="drv_001",
            vehicle_id="veh_001",
            drowsiness_score=0.89,
            distraction_score=0.76,
            yawning_score=0.7,
            phone_usage_score=0.9,
            speed_kph=88.0,
            timestamp_ms=1000,
        )

        result = monitor.evaluate(signal, now_ms=1000)

        self.assertEqual(result.risk_level, DriverRiskLevel.HIGH)
        self.assertIn("drowsiness_high", result.reasons)
        self.assertIn("distraction_high", result.reasons)

    def test_build_capture_candidates_prefers_selected_index(self) -> None:
        candidates = build_capture_candidates(1)
        self.assertEqual(candidates[0], 1)
        self.assertIn(0, candidates)
        self.assertIn(1, candidates)


if __name__ == "__main__":
    unittest.main()
