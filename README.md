# NETRA AI

NETRA AI is an AI-first driver monitoring system focused on detecting unsafe driving behavior and routing alerts through cloud and satellite communication channels.

## Overview

This project is designed around a simple and focused architecture:

- AI monitoring of driver behavior
- Risk evaluation based on drowsiness, distraction, speeding, and phone-use signals
- Cloud transmission for normal and moderate-risk alerts
- Satellite transmission for high-risk and emergency escalation
- Audit logging for monitoring and traceability

## Core Files

- `safety_core.py` - AI risk logic and driver behavior scoring
- `fleet_gatekeeper_hub.py` - orchestration layer for signal ingestion and transmission routing
- `webcam_camera_test.py` - basic webcam/camera validation utility
- `tests/test_safety_core.py` - regression tests for driver monitoring behavior

## How it works

1. Driver signals are collected from a source such as camera or telemetry input.
2. The monitoring logic evaluates behavioral risk.
3. A risk score is calculated with reasons such as:
   - `drowsiness_high`
   - `distraction_high`
   - `yawning_detected`
   - `phone_usage_detected`
   - `speeding_detected`
4. The system chooses the transmission mode:
   - `cloud` for normal/moderate conditions
   - `satellite` for high-risk conditions
   - `hybrid` for dual transmission when needed
5. Events are written to the audit log for review.

## Example run

```bash
python fleet_gatekeeper_hub.py --driver-id drv_001 --vehicle-id veh_001 --drowsiness-score 0.82 --distraction-score 0.74 --speed-kph 82
```

## Risk levels

The system currently maps events into these levels:

- `NORMAL`
- `MODERATE`
- `HIGH`

## Project status

This repository is intentionally minimized to the AI monitoring and transmission scope. It is not a full fleet management platform or legacy hardware gatekeeper implementation.

## License

This project is for internal prototype and research use.
