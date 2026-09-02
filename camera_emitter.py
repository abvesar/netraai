import os
import time

import cv2
import requests

from driver_monitor import DrishtiAIDMS

REMOTE_DASHBOARD_URL = os.getenv("REMOTE_DASHBOARD_URL", "http://localhost:8000/api/driver-status")
DRIVER_ID = os.getenv("DRIVER_ID", "drv_001")
SEND_INTERVAL_SECONDS = float(os.getenv("SEND_INTERVAL_SECONDS", "0.5"))


def build_payload(alerts):
    drowsy = bool(alerts.get("drowsy", False))
    distracted = bool(alerts.get("distracted", False))
    yawning = bool(alerts.get("yawning", False))
    fatigue_score = float(alerts.get("fatigue_score", 0.0) or 0.0)

    if drowsy or distracted or yawning:
        status = "ALERT"
        if drowsy:
            risk_level = "HIGH"
        elif distracted:
            risk_level = "MODERATE"
        else:
            risk_level = "MODERATE"
    else:
        status = "NORMAL"
        risk_level = "NORMAL"

    return {
        "driver_id": DRIVER_ID,
        "status": status,
        "drowsy": drowsy,
        "distracted": distracted,
        "yawning": yawning,
        "fatigue_score": round(fatigue_score, 3),
        "risk_level": risk_level,
    }


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Unable to open local webcam. Check camera permissions or index 0.")

    detector = DrishtiAIDMS()
    print(f"Sending AI telemetry to {REMOTE_DASHBOARD_URL}")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Lost webcam frame, retrying...")
                time.sleep(1)
                continue

            alerts = detector.process_frame(frame)
            payload = build_payload(alerts)

            try:
                response = requests.post(REMOTE_DASHBOARD_URL, json=payload, timeout=5)
                response.raise_for_status()
                print(f"telemetry sent: {payload['risk_level']} fatigue={payload['fatigue_score']}")
            except Exception as exc:
                print(f"failed to send telemetry: {exc}")

            time.sleep(SEND_INTERVAL_SECONDS)
    finally:
        cap.release()


if __name__ == "__main__":
    main()
