# NetraAI Software Architecture Standards (Prototype)

## 1) Layered Structure (Hardware Abstraction)

- Application/Safety Layer:
  - `safety_core.py`
  - `fleet_gatekeeper_hub.py` (application service + abstract ports)
  - Contains deterministic policy and domain decisions.
  - No GPIO, CAN driver, or camera transport code.
- Adapter Layer (ECU/BSW-like ports):
  - `can_virtual_sim.py` (CAN transport adapter)
  - `hikvision_isapi.py` (ISAPI transport adapter)
  - `gatekeeper_scaffold.py` (GPIO adapter in dry-run by default)
  - `fleet_gatekeeper_hub.py` adapters:
    - `PythonCanVehicleNetworkAdapter`
    - `HikvisionInterventionAdapter`
    - `JsonlAuditLogAdapter`
- Composition Layer:
  - `remote_intervention_sim.py`
  - `fleet_gatekeeper_hub.py::main()`
  - Wires policy + adapters for scenario execution.

This split allows replacing Raspberry Pi GPIO or virtual CAN with industrial ECU drivers later without changing decision policy.

### Port Contracts (SWC-to-BSW boundary)

`fleet_gatekeeper_hub.py` defines hardware-agnostic ports:
- `AlcoholSensorPort`
- `VehicleNetworkPort`
- `ImmobilizerPort`
- `CameraInterventionPort`
- `AuditLogPort`

These ports are stable interfaces. MCU/BSW changes should occur only in adapter implementations, not in safety policy or orchestration logic.

## 2) Safety-First Rules (Fail-Safe)

Implemented in `SafetyGatekeeper`:
- Default-deny behavior for uncertainty.
- Deny on sensor fault.
- Deny on uncalibrated state.
- Deny on stale sample.
- Deny on out-of-range sample.
- Deny on alcohol above threshold.
- Allow only when all checks pass.

The policy always returns:
- decision: `ALLOW` or `DENY`
- reasons: deterministic reason codes for audit logs and diagnostics.

## 3) AUTOSAR-Style Alignment (Prototype Mapping)

- SWC-like application logic: `SafetyGatekeeper` in `safety_core.py`
- SWC-like orchestration service: `FleetGatekeeperHubService` in `fleet_gatekeeper_hub.py`
- RTE-like composition: `remote_intervention_sim.py`, `fleet_gatekeeper_hub.py::main()`
- BSW/MCAL-like adapters: CAN, GPIO, and ISAPI modules (`can_virtual_sim.py`, `hikvision_isapi.py`, adapter classes)

While not full AUTOSAR, this architecture follows core AUTOSAR intent: portability, isolation of hardware, deterministic behavior, and traceable decisions.

## 4) Safety-First Coding Requirements (Immobilizer Critical)

- Fail-safe default actuation: relay/immobilizer must start each cycle in DENY/OFF state.
- Deterministic decisions only: no probabilistic decision path may directly control immobilization.
- Explicit reason codes: every ALLOW/DENY must include machine-readable reasons.
- Immutable audit stream: append-only decision events with sequence IDs and timestamps.
- Input validation at boundary: stale, out-of-range, uncalibrated, or unhealthy inputs must map to DENY.
- Adapter failure containment: transport/API failures (CAN, ISAPI, GPIO) must not produce ALLOW.
- Time-bounded operations: external IO calls must enforce finite timeouts.
- Separation of concerns: policy module must remain independent from transport and hardware APIs.

## 5) Production Hardening Backlog

- Add immutable event logging with sequence IDs.
- Add watchdog/heartbeat and adapter health supervision.
- Add configurable safety profiles per fleet region.
- Add integration tests with replayed CAN and ISAPI traces.
- Add secure secrets management for camera credentials.
