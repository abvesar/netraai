# Virtual CAN Development Guide (SocketCAN + python-can)

This guide lets you simulate commercial-vehicle CAN traffic before connecting to real truck hardware.

## 1) Install Dependencies

On Linux / Raspberry Pi:

```bash
sudo apt-get update
sudo apt-get install -y can-utils
python3 -m pip install python-can
```

On this project, use your virtual environment as needed.

## 2) Create Virtual CAN Interface (vcan0)

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
ip -details link show vcan0
```

To tear it down:

```bash
sudo ip link del vcan0
```

## 3) Message Map Used by Simulation

- 0x100: Engine Start Request
  - Byte0: 1 = start request
- 0x101: Hub Override
  - Byte0: 1 = allow, 0 = block
- 0x102: Engine Status
  - Byte0 values:
    - 0 = STOPPED
    - 1 = RUNNING
    - 2 = START_REQUESTED
    - 3 = START_BLOCKED
  - Byte1: vehicle node id

## 4) Run the Python CAN Simulation

File: can_virtual_sim.py

### A) Single-process demo

```bash
python can_virtual_sim.py --mode demo --interface socketcan --channel vcan0 --sensor-value 0.42 --threshold 0.5
```

### B) Multi-node simulation across terminals

Terminal 1 (monitor all traffic):

```bash
python can_virtual_sim.py --mode monitor --interface socketcan --channel vcan0 --max-messages 200
```

Terminal 2 (Gatekeeper hub node):

```bash
python can_virtual_sim.py --mode hub --interface socketcan --channel vcan0 --sensor-value 0.80 --threshold 0.5 --max-messages 100
```

Hub with Hikvision/Prama ISAPI active interventions enabled:

```bash
python can_virtual_sim.py --mode hub --interface socketcan --channel vcan0 \
  --sensor-value 0.80 --threshold 0.5 \
  --camera-enabled --camera-base-url http://192.168.1.10 \
  --camera-username admin --camera-password your_password \
  --snapshot-file artifacts/intervention_frame.jpg
```

For safe local testing without touching a real camera:

```bash
python can_virtual_sim.py --mode demo --interface virtual --channel vcan0 \
  --sensor-value 0.80 --threshold 0.5 \
  --camera-enabled --camera-base-url http://127.0.0.1 \
  --camera-username admin --camera-password admin --camera-dry-run
```

Terminal 3 (vehicle node requesting start):

```bash
python can_virtual_sim.py --mode vehicle --interface socketcan --channel vcan0 --request-interval 2.0 --status-interval 1.0 --max-messages 20
```

Change sensor-value below threshold to simulate access allowed.

## 5) SocketCAN CLI Monitoring Tools

Use can-utils:

```bash
candump vcan0
cansend vcan0 100#0100000000000000
```

These are useful alongside Python simulation.

## 6) GUI Monitoring Tools

- CanKing can be used where supported for frame visualization and diagnostics.
- Any SocketCAN-compatible monitor can be used to inspect IDs 0x100, 0x101, 0x102.

## 7) Safety Behavior

The hub simulation enforces fail-safe behavior:

- If sensor value is above threshold, hub emits Override=0 and Engine Status=START_BLOCKED.
- If below threshold, hub emits Override=1 and Engine Status=RUNNING.
- On each start request, the hub requests a live frame over ISAPI for facial-verification flow.
- On DENY, the hub triggers ISAPI alarm output and camera audio intervention.

This mirrors the ignition interlock concept used in fleet safety systems.

## 8) Platform Note

- Linux/Raspberry Pi with SocketCAN (`interface=socketcan`, `channel=vcan0`) supports multi-process CAN testing.
- On Windows, python-can `virtual` backend is process-local; use `--mode demo` for deterministic end-to-end validation in one process.
