# DRISHTI AI

DRISHTI AI is an AI-first driver monitoring prototype focused on detecting driver fatigue, distraction, speeding, and risky behavior, then routing alerts through cloud, satellite, or hybrid communication flows.

## Overview

This project is a lightweight monitoring prototype designed for experimentation and demonstration. It combines:

- AI-based signal evaluation from camera or telemetry inputs
- risk scoring for drowsiness, distraction, yawning, phone use, and speeding
- cloud, satellite, and hybrid transmission decisions
- JSONL audit logging for traceability
- a live browser dashboard plus a remote stream demo path

## Architecture

The current design follows an AI-first monitoring model:

- Application/Monitoring Layer: [safety_core.py](safety_core.py), [fleet_gatekeeper_hub.py](fleet_gatekeeper_hub.py)
- Transport Layer: cloud, satellite, and hybrid adapters in [fleet_gatekeeper_hub.py](fleet_gatekeeper_hub.py)
- Audit Layer: JSONL event logging via the audit adapter in [fleet_gatekeeper_hub.py](fleet_gatekeeper_hub.py)
- Vision Layer: [driver_monitor.py](driver_monitor.py) for MediaPipe-based face analysis
- Dashboard Layer: [driver_monitor_dashboard.py](driver_monitor_dashboard.py) for the browser UI and live status feed
- Remote Demo Layer: [demo_stream_server.py](demo_stream_server.py) and [demo_remote_camera_sender.py](demo_remote_camera_sender.py)

## Core files

- [safety_core.py](safety_core.py) — risk scoring and monitoring logic for drowsiness, distraction, yawning, phone use, and speeding
- [fleet_gatekeeper_hub.py](fleet_gatekeeper_hub.py) — orchestration layer, transmission adapters, and CLI entry point
- [driver_monitor.py](driver_monitor.py) — MediaPipe-based face monitoring prototype for live driver-state detection
- [driver_monitor_dashboard.py](driver_monitor_dashboard.py) — dashboard backend, status API, and frame-processing loop
- [demo_stream_server.py](demo_stream_server.py) — sample MJPEG stream server that serves uploaded frames from a remote camera
- [demo_remote_camera_sender.py](demo_remote_camera_sender.py) — sample sender that uploads JPEG frames from a remote device to the demo stream server
- [webcam_camera_test.py](webcam_camera_test.py) — webcam/network validation utility
- [start_drishiti.ps1](start_drishiti.ps1) — one-click Windows launcher for the monitoring hub
- [tests/test_safety_core.py](tests/test_safety_core.py) — regression tests for the core risk engine

## How the monitoring works

1. A driver signal is generated from a live camera stream, remote feed, or telemetry input.
2. The AI monitor evaluates signals such as:
   - drowsiness_high
   - distraction_high
   - yawning_detected
   - phone_usage_detected
   - speeding_detected
3. A risk level is assigned:
   - NORMAL
   - MODERATE
   - HIGH
4. The transmission layer routes the event:
   - cloud for routine or moderate-risk events
   - satellite for high-risk or emergency escalation
   - hybrid for dual transmission when needed
5. The event is written to the audit log for downstream review.

## Quick start

### 1) Use the project virtual environment

From the project root:

```powershell
.venv\Scripts\python.exe --version
```

### 2) Run the monitoring hub directly

```powershell
& ".venv\Scripts\python.exe" fleet_gatekeeper_hub.py --driver-id drv_001 --vehicle-id veh_001 --drowsiness-score 0.82 --distraction-score 0.74 --yawning-score 0.2 --phone-usage-score 0.1 --speed-kph 82 --max-cycles 1 --transmission-mode cloud
```

### 3) Start the demo remote camera stream

This is useful when no local webcam is available.

```powershell
cd "C:\Users\ROHIT\OneDrive\Desktop\DRISHTI AI"
& ".venv\Scripts\python.exe" demo_stream_server.py --host 0.0.0.0 --port 9000
```

Then send frames from another device or process:

```powershell
& ".venv\Scripts\python.exe" demo_remote_camera_sender.py --camera-url http://<remote-camera-ip>:8080/shot --upload-url http://<host-ip>:9000/upload --interval-seconds 0.5 --limit 50
```

### 4) Start the dashboard with the remote stream

```powershell
cd "C:\Users\ROHIT\OneDrive\Desktop\DRISHTI AI"
& ".venv\Scripts\python.exe" driver_monitor_dashboard.py --host 0.0.0.0 --port 9001 --stream-url http://127.0.0.1:9000/feed
```

Open the browser at:

- http://localhost:9001/
- or http://<your-machine-ip>:9001/ on the local network

### 5) One-click Windows launch

```powershell
powershell -ExecutionPolicy Bypass -File .\start_drishiti.ps1
```

### 6) Run the tests

```powershell
& ".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -q
```

## Example output

```text
cloud_tx driver_id=drv_001 risk=HIGH reasons=['drowsiness_high', 'distraction_high']
ai_monitor sequence_id=1 driver_id=drv_001 risk=HIGH reasons=drowsiness_high,distraction_high
```

## Current project status

This repository is a focused prototype for AI-based driver monitoring, alert routing, and local experimentation. It is not a full commercial fleet platform or a hardware immobilizer system.

## Notes

- The app can run with either a local camera or a remote stream feed.
- The demo stream server is designed to support a remote-device webcam scenario when the local machine cannot access a camera directly.
- For public internet sharing, the app still requires a public-facing host or tunnel for the dashboard/stream endpoints.

## License

This project is intended for prototype, research, and internal evaluation use.
