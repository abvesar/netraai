# DRISHTI AI Software Architecture Standards (Prototype)

## 1) DRISHTI AI V2 Architecture: AI Monitoring First

DRISHTI AI is now structured around AI-first driver behavior monitoring instead of a hardware immobilizer gatekeeper pattern.

- Application/Monitoring Layer:
  - `safety_core.py`
  - `fleet_gatekeeper_hub.py`
  - Contains AI decision logic for drowsiness, distraction, speeding, and unsafe behavior detection.
  - No direct starter/relay logic is required in the initial release.
- Transport Layer:
  - `CloudTransmissionAdapter` for cloud-based alert delivery.
  - `SatelliteTransmissionAdapter` for satellite-based emergency transmission.
  - `HybridTransmissionAdapter` for dual-mode transmission during severe risk events.
- Audit Layer:
  - `JsonlAuditLogAdapter` stores driver monitor events with timestamps and risk metadata.
- Composition Layer:
  - `fleet_gatekeeper_hub.py::main()` wires the AI model, signal source, and transmission adapters together.

This initial release keeps the system deliberately simple: AI models detect the risk, and telemetry is sent through cloud or satellite channels depending on severity.

## 2) AI-First Risk Rules

Implemented in `DriverBehaviorMonitor`:
- High drowsiness score triggers a drowsiness alert.
- High distraction score triggers a distraction alert.
- Yawning, phone use, and speeding increase the risk score.
- High risk routes the alert through satellite transmission.
- Moderate risk uses cloud transmission.
- Normal behavior remains low-alert and cloud-transmitted only if needed.

## 3) Output Contract

The driver monitoring pipeline returns:
- `risk_level`: `NORMAL`, `MODERATE`, or `HIGH`
- `reasons`: machine-readable event codes
- `confidence`: AI confidence score
- `recommended_transmission`: `cloud` or `satellite`

## 4) Transmission Design

The initial DRISHTI AI network design keeps transmission modes specific and lightweight:
- Cloud mode: routine telemetry and moderate risk events.
- Satellite mode: severe risk events, poor connectivity, or emergency alert escalation.
- Hybrid mode: send both the cloud and satellite copy when a high-risk event is detected.

## 5) Hardening Backlog

- Add an edge AI model ingestion pipeline for video and sensor streams.
- Add secure cloud authentication and message signing.
- Add regional outage fallback between cloud and satellite paths.
- Add replayable test traces for driver behavior scenarios.
- Add fleet-level severity routing and on-call escalation flows.
