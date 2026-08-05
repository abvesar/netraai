# NetraAI Dev Environment and Simulation Runbook

## 1) Environment Setup

In the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install python-can hikvision-isapi-cli
```

## 2) Virtual Truck Simulation

Script: virtual_truck_sim.py

Purpose:
- Simulates a truck node sending periodic engine status and start requests on virtual CAN.

Example:

```powershell
.\.venv\Scripts\python.exe .\virtual_truck_sim.py --interface virtual --channel vcan0 --cycles 5 --request-interval 1.5 --status-interval 0.5
```

CAN frames sent:
- 0x102 Engine Status
- 0x100 Engine Start Request

## 3) Security Loop Simulation

Script: security_loop_sim.py

Core rule:
- Relay closes (ignition unlock) only if both simulated signals are true:
  - sobriety_ok == True
  - facial_ok == True

Allow case:

```powershell
.\.venv\Scripts\python.exe .\security_loop_sim.py --sobriety-ok --facial-ok --cycles 1
```

Deny case (facial false):

```powershell
.\.venv\Scripts\python.exe .\security_loop_sim.py --sobriety-ok --cycles 1
```

Deny case (both false):

```powershell
.\.venv\Scripts\python.exe .\security_loop_sim.py --cycles 1
```

## 4) Linux/Raspberry Pi SocketCAN Notes

For multi-process bus integration tests on Linux/RPi:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Then run scripts with:
- --interface socketcan
- --channel vcan0

## 5) One-Command Integrated Scenario

Script:
- integrated_scenario_runner.py

This runs three roles together in one process:
- Virtual Truck sender
- Edge Gatekeeper decision bridge
- Hub intervention listener (ISAPI dry-run by default)

Deny scenario (simulated alcohol above threshold):

```powershell
.\.venv\Scripts\python.exe .\integrated_scenario_runner.py --requests 3 --mock-voltage 1.60 --clean-air-voltage 1.00 --threshold-brac 0.02
```

Allow scenario (simulated alcohol below threshold):

```powershell
.\.venv\Scripts\python.exe .\integrated_scenario_runner.py --requests 3 --mock-voltage 1.20 --clean-air-voltage 1.00 --threshold-brac 0.02
```
