import os
import time

from flask import Flask, Response, render_template_string
import cv2
import numpy as np
from ai_tracking.driver_monitor import DrishtiAIDMS

app = Flask(__name__)
dms_system = DrishtiAIDMS()

camera_source = os.environ.get("DRISHTI_CAMERA_SOURCE", "0")
if camera_source.isdigit():
    camera_source = int(camera_source)
camera = None
pipeline_error = None


def _open_camera():
    global camera
    if camera is not None and camera.isOpened():
        return camera

    if isinstance(camera_source, int):
        camera = cv2.VideoCapture(camera_source, cv2.CAP_DSHOW)
    else:
        camera = cv2.VideoCapture(camera_source)
    if not camera.isOpened():
        camera.release()
        camera = None
    return camera


def _placeholder_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (18, 20, 30)
    cv2.putText(frame, "DRISHTI AI CAMERA UNAVAILABLE", (75, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 180, 255), 2)
    cv2.putText(frame, "Check webcam access or DRISHTI_CAMERA_SOURCE", (42, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)
    return frame


def _is_black_frame(frame) -> bool:
    return float(frame.mean()) < 3.0 and int(frame.max()) < 32


def generate_frames():
    global camera, pipeline_error
    while True:
        active_camera = _open_camera()
        if active_camera is None:
            frame = _placeholder_frame()
            time.sleep(0.5)
        else:
            success, frame = active_camera.read()
            if not success:
                active_camera.release()
                camera = None
                frame = _placeholder_frame()
                time.sleep(0.5)
            else:
                alerts = None
                if _is_black_frame(frame):
                    alerts = {
                        "drowsy": False,
                        "distracted": False,
                        "face_recognized": False,
                        "driver_id": "CAMERA FRAME BLACK",
                        "drowsiness_confidence": 0.0,
                    }
                    cv2.putText(
                        frame,
                        "CAMERA INPUT IS BLACK: OPEN SHUTTER / CHECK PERMISSIONS",
                        (25, 135),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 180, 255),
                        2,
                    )
                elif pipeline_error is None:
                    try:
                        alerts = dms_system.process_frame(frame)
                    except (FileNotFoundError, ImportError, RuntimeError) as exc:
                        pipeline_error = str(exc)

        if active_camera is None or not success or pipeline_error is not None:
            alerts = {
                "drowsy": False,
                "distracted": False,
                "face_recognized": False,
                "driver_id": "CAMERA UNAVAILABLE" if active_camera is None else "AI MODEL UNAVAILABLE",
                "drowsiness_confidence": 0.0,
                "face_detected": False,
            }
            if pipeline_error is not None and active_camera is not None and success:
                cv2.putText(
                    frame,
                    "AI MODEL UNAVAILABLE: add yolov8n-face.pt",
                    (30, 130),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 180, 255),
                    2,
                )
        if alerts["drowsy"]:
            if int(time.monotonic() * 4) % 2 == 0:
                cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 8)
            status_text = "CRITICAL: DROWSINESS DETECTED"
            status_color = (0, 0, 255)
        elif alerts["distracted"]:
            status_text = "WARNING: DISTRACTED DRIVING"
            status_color = (0, 165, 255)
        elif not alerts.get("face_detected", False):
            status_text = "NO FACE DETECTED"
            status_color = (0, 180, 255)
        else:
            status_text = "MEDIAPIPE FACE MESH ACTIVE"
            status_color = (0, 255, 0)

        cv2.putText(frame, status_text, (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)
        recognition_text = alerts["driver_id"]
        recognition_color = (0, 220, 80) if alerts["face_recognized"] else (0, 80, 255)
        cv2.putText(
            frame,
            f"DRIVER ID: {recognition_text}",
            (30, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            recognition_color,
            2,
        )
        device_name = "MEDIAPIPE CPU"
        cv2.putText(
            frame,
            f"Device Engine: {device_name}",
            (30, frame.shape[0] - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )

        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )

@app.route('/video_feed')
def video_feed():
    # Returns the streaming response using the content type multipart/x-mixed-replace
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    # A quick HTML layout simulating your Central Management Dashboard UI
    dashboard_html = """
    <html>
    <head>
        <title>DRISHTI AI Central Fleet Command</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #121214; color: #fff; padding: 20px; }
            .dashboard-container { max-width: 1200px; margin: auto; display: flex; gap: 20px; }
            .video-card { background: #1e1e24; border-radius: 12px; padding: 15px; border: 1px solid #2e2e38; }
            .telemetry-card { flex: 1; background: #1e1e24; border-radius: 12px; padding: 15px; border: 1px solid #2e2e38; }
            h1, h2 { color: #00ff66; margin-top: 0; }
            .status-badge { background: #00ff66; color: #121214; padding: 5px 10px; border-radius: 5px; font-weight: bold; }
            .remote-link { margin-top: 12px; font-size: 14px; color: #aaffcc; }
        </style>
    </head>
    <body>
        <h1>DRISHTI AI Operations Dashboard <span class="status-badge">Live Connection</span></h1>
        <div class="remote-link">Remote access URL: http://&lt;this-machine-ip&gt;:5000/</div>
        <div class="dashboard-container">
            <!-- The Live Cam Stream Card -->
            <div class="video-card">
                <h2>In-Cab Vehicle Feed (Vehicle #VEH-001)</h2>
                <!-- The magic happens here: Pointing directly to our Flask Python video route -->
                <img src="/video_feed" width="640" height="480" style="border-radius: 8px; border: 2px solid #2e2e38;" />
            </div>
            
            <!-- Mock Telemetry Panel to look like a full startup system -->
            <div class="telemetry-card">
                <h2>Telemetry Signals</h2>
                <p><strong>Driver ID:</strong> drv_001 (Verified via FaceID)</p>
                <p><strong>Ignition State:</strong> UNLOCKED (Breathalyzer Passed: 0.00% BAC)</p>
                <p><strong>Current Speed:</strong> 62 km/h</p>
                <hr style="border-color: #2e2e38;">
                <button style="background: #ff3333; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; cursor: pointer;">
                    Remote Intervene: Push Cab Audio
                </button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(dashboard_html)

if __name__ == '__main__':
    # Start the server on port 5000
        port = int(os.environ.get("DRISHTI_PORT", "5000"))
        app.run(host="0.0.0.0", port=port, debug=False)
