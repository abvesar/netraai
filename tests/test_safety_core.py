from __future__ import annotations

import unittest

from safety_core import SafetyDecision, SafetyGatekeeper, SafetyPolicyConfig, SensorReading


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


if __name__ == "__main__":
    unittest.main()
