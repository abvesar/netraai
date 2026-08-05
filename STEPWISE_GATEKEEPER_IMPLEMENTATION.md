# NetraAI Stepwise Implementation (Edge + CAN + ISAPI + Safety)

## Step 1: Ignition Control and Sobriety Check (Edge Logic)

Primary script:
- gatekeeper_primary.py

What is implemented:
- MQ-3 warm-up / burn-in gate (configurable hours).
- Clean-air calibration routine (`--calibrate-only`) to write baseline voltage.
- Continuous loop that reads analog voltage and estimates BrAC.
- Relay OFF by default and relay OFF on any deny/failure condition.

Recommended edge dependencies (Raspberry Pi):

```bash
python3 -m pip install RPi.GPIO adafruit-circuitpython-ads1x15
```

Calibration (clean air):

```bash
python gatekeeper_primary.py \
  --burn-in-hours 24 \
  --calibrate-only \
  --calibration-samples 30 \
  --calibration-state-file artifacts/mq3_calibration_state.json
```

Run sobriety loop:

```bash
python gatekeeper_primary.py \
  --threshold-brac 0.02 \
  --brac-per-volt-delta 0.04 \
  --burn-in-hours 24 \
  --calibration-state-file artifacts/mq3_calibration_state.json
```

## Step 2: Vehicle Interaction via Virtual CAN

Virtual truck simulator:
- virtual_truck_sim.py

Edge CAN bridge:
- edge_gatekeeper_can_bridge.py

On Linux/Raspberry Pi create virtual CAN interface:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Run edge CAN bridge (intercepts 0x100 request, publishes 0x101 override):

```bash
python edge_gatekeeper_can_bridge.py \
  --interface socketcan --channel vcan0 \
  --threshold-brac 0.02 --brac-per-volt-delta 0.04 \
  --calibration-state-file artifacts/mq3_calibration_state.json
```

Run virtual truck:

```bash
python virtual_truck_sim.py --interface socketcan --channel vcan0 --cycles 20
```

## Step 3: Centralized Monitoring and Intervention (ISAPI)

ISAPI transport module:
- hikvision_isapi.py

Hub intervention simulation:
- can_virtual_sim.py (camera-enabled modes)
- fleet_gatekeeper_hub.py (port/adapter architecture)

Implemented ISAPI actions:
- Snapshot retrieval for identity verification workflow.
- Alarm output trigger on deny decisions.
- Speaker text broadcast for active intervention.

Example:

```bash
python fleet_gatekeeper_hub.py \
  --sensor-value 0.9 --threshold 0.5 --max-cycles 1 \
  --camera-enabled \
  --camera-base-url http://192.168.1.10 \
  --camera-username admin --camera-password <password>
```

## Step 4: Safety-Critical Standards and Compliance

Automated gates implemented:
- .github/workflows/safety-ci.yml
- tests/test_safety_core.py
- tests/test_security_loop_sim.py

Current gates:
- Syntax compilation check.
- Unit tests for deterministic allow/deny decisions.
- Unit tests for relay-close-only-when-both-signals-true rule.

Security-by-design controls to enforce in deployment:
- Use HTTPS/TLS for ISAPI and keep certificate verification enabled.
- Store secrets in environment variables or vault, not in code.
- Use signed OS image and secure boot on edge hardware.
- Restrict CAN and camera control services with least privilege.
- Persist immutable audit logs for each safety decision.

MISRA/AUTOSAR alignment guidance:
- Keep decision policy deterministic and side-effect free.
- Keep hardware adapters isolated behind interfaces/ports.
- Default to DENY/OFF on uncertainty, stale data, or IO errors.
