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


class DriverRiskLevel(str, Enum):
    NORMAL = "NORMAL"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True)
class DriverBehaviorSignal:
    driver_id: str
    vehicle_id: str
    drowsiness_score: float = 0.0
    distraction_score: float = 0.0
    yawning_score: float = 0.0
    phone_usage_score: float = 0.0
    speed_kph: float = 0.0
    timestamp_ms: int = 0


@dataclass(frozen=True)
class DriverBehaviorAssessment:
    risk_level: DriverRiskLevel
    reasons: List[str]
    confidence: float
    recommended_transmission: str = "cloud"

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level == DriverRiskLevel.HIGH


class DriverBehaviorMonitor:
    """AI-only monitoring layer for drowsiness, distraction, and unsafe driving events."""

    def __init__(
        self,
        drowsiness_threshold: float = 0.7,
        distraction_threshold: float = 0.65,
        yawning_threshold: float = 0.6,
        phone_usage_threshold: float = 0.8,
        speeding_threshold_kph: float = 100.0,
        max_signal_age_ms: int = 5000,
    ) -> None:
        self.drowsiness_threshold = drowsiness_threshold
        self.distraction_threshold = distraction_threshold
        self.yawning_threshold = yawning_threshold
        self.phone_usage_threshold = phone_usage_threshold
        self.speeding_threshold_kph = speeding_threshold_kph
        self.max_signal_age_ms = max_signal_age_ms

    def evaluate(self, signal: DriverBehaviorSignal, now_ms: int) -> DriverBehaviorAssessment:
        reasons: List[str] = []
        risk_score = 0.0

        if signal.drowsiness_score >= self.drowsiness_threshold:
            reasons.append("drowsiness_high")
            risk_score += 0.45

        if signal.distraction_score >= self.distraction_threshold:
            reasons.append("distraction_high")
            risk_score += 0.35

        if signal.yawning_score >= self.yawning_threshold:
            reasons.append("yawning_detected")
            risk_score += 0.10

        if signal.phone_usage_score >= self.phone_usage_threshold:
            reasons.append("phone_usage_detected")
            risk_score += 0.20

        if signal.speed_kph >= self.speeding_threshold_kph:
            reasons.append("speeding_detected")
            risk_score += 0.15

        if now_ms - signal.timestamp_ms > self.max_signal_age_ms:
            reasons.append("stale_signal")
            risk_score += 0.25

        if not reasons:
            return DriverBehaviorAssessment(
                risk_level=DriverRiskLevel.NORMAL,
                reasons=["behavior_normal"],
                confidence=0.96,
                recommended_transmission="cloud",
            )

        if risk_score >= 0.8:
            risk_level = DriverRiskLevel.HIGH
            recommended_transmission = "satellite"
        elif risk_score >= 0.45:
            risk_level = DriverRiskLevel.MODERATE
            recommended_transmission = "cloud"
        else:
            risk_level = DriverRiskLevel.NORMAL
            recommended_transmission = "cloud"

        confidence = min(0.99, 0.65 + (risk_score * 0.5))
        return DriverBehaviorAssessment(
            risk_level=risk_level,
            reasons=reasons,
            confidence=round(confidence, 3),
            recommended_transmission=recommended_transmission,
        )
