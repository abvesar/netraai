from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class SafetyDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class SensorReading:
    value: float
    timestamp_ms: int
    facial_verified: bool = True
    sensor_ok: bool = True
    is_calibrated: bool = True


@dataclass(frozen=True)
class SafetyPolicyConfig:
    alcohol_threshold: float = 0.5
    max_sample_age_ms: int = 5000
    require_calibration: bool = True
    valid_range_min: float = 0.0
    valid_range_max: float = 1.0


@dataclass(frozen=True)
class SafetyDecisionResult:
    decision: SafetyDecision
    reasons: List[str]

    @property
    def allowed(self) -> bool:
        return self.decision == SafetyDecision.ALLOW


class SafetyGatekeeper:
    """Deterministic fail-safe policy: any uncertainty leads to DENY."""

    def __init__(self, config: SafetyPolicyConfig) -> None:
        self.config = config

    def evaluate(self, reading: SensorReading, now_ms: int) -> SafetyDecisionResult:
        reasons: List[str] = []

        if not reading.sensor_ok:
            reasons.append("sensor_not_healthy")

        if not reading.facial_verified:
            reasons.append("facial_not_verified")

        if self.config.require_calibration and not reading.is_calibrated:
            reasons.append("sensor_not_calibrated")

        if reading.value < self.config.valid_range_min or reading.value > self.config.valid_range_max:
            reasons.append("sensor_value_out_of_range")

        sample_age = max(0, now_ms - reading.timestamp_ms)
        if sample_age > self.config.max_sample_age_ms:
            reasons.append("sensor_sample_stale")

        if reading.value >= self.config.alcohol_threshold:
            reasons.append("alcohol_above_threshold")

        if reasons:
            return SafetyDecisionResult(decision=SafetyDecision.DENY, reasons=reasons)

        return SafetyDecisionResult(decision=SafetyDecision.ALLOW, reasons=["all_checks_passed"])
