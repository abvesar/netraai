from __future__ import annotations

import argparse
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

import cv2

from safety_core import DriverBehaviorMonitor, DriverBehaviorSignal


def build_capture_candidates(preferred_index: int = 0) -> list[int]:
    candidates: list[int] = []
    seen: set[int] = set()
    for index in [preferred_index, 0, 1, 2, 3, -1]:
        if index not in seen and index >= -1:
            candidates.append(index)
            seen.add(index)
    return candidates


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[bytes] = None

    def set(self, frame: bytes) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._frame


class DriverAIController:
    def __init__(
        self,
        camera_index: int = 0,
        drowsiness_score: float = 0.82,
        distraction_score: float = 0.74,
        yawning_score: float = 0.6,
        phone_usage_score: float = 0.2,
        speed_kph: float = 82.0,
    ) -> None:
        self.camera_index = camera_index
        self.monitor = DriverBehaviorMonitor()
        self.frame_store = FrameStore()
        self.last_status: dict[str, object] = {
            "risk_level": "HIGH",
            "reasons": ["drowsiness_high", "distraction_high"],
            "confidence": 0.91,
            "recommended_transmission": "satellite",
        }
        self._stop_event = threading.Event()
        self._loop_thread = threading.Thread(target=self._camera_loop, daemon=True)

        self.drowsiness_score = drowsiness_score
        self.distraction_score = distraction_score
        self.yawning_score = yawning_score
        self.phone_usage_score = phone_usage_score
        self.speed_kph = speed_kph

    def start(self) -> None:
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _camera_loop(self) -> None:
        cap = self._open_camera()
        if cap is None:
            self._write_placeholder_frame()
            self._update_status_from_scores()
            return

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    break

                ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    self.frame_store.set(encoded.tobytes())
                self._update_status_from_scores()
                time.sleep(0.2)
        finally:
            cap.release()
            if not self._stop_event.is_set():
                self._write_placeholder_frame()
                self._update_status_from_scores()

    def _open_camera(self):
        candidates = build_capture_candidates(self.camera_index)
        for index in candidates:
            for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]:
                try:
                    cap = cv2.VideoCapture(index, backend)
                except Exception:
                    continue
                if not cap.isOpened():
                    cap.release()
                    continue
                for _ in range(3):
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        return cap
                    time.sleep(0.05)
                cap.release()
        return None

    def _write_placeholder_frame(self) -> None:
        width, height = 640, 480
        canvas = __import__("numpy").zeros((height, width, 3), dtype="uint8")
        canvas[:] = (18, 20, 30)
        cv2.putText(canvas, "NETRA AI DRIVER VIEW", (85, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 2)
        cv2.putText(canvas, "Camera unavailable - checking device", (90, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 210, 255), 2)
        cv2.putText(canvas, "AI risk engine active", (150, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 255, 160), 2)
        ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            self.frame_store.set(encoded.tobytes())

    def _update_status_from_scores(self) -> None:
        signal = DriverBehaviorSignal(
            driver_id="drv_demo",
            vehicle_id="veh_demo",
            drowsiness_score=self.drowsiness_score,
            distraction_score=self.distraction_score,
            yawning_score=self.yawning_score,
            phone_usage_score=self.phone_usage_score,
            speed_kph=self.speed_kph,
            timestamp_ms=int(time.time() * 1000),
        )
        assessment = self.monitor.evaluate(signal=signal, now_ms=int(time.time() * 1000))
        self.last_status = {
            "risk_level": assessment.risk_level.value,
            "reasons": assessment.reasons,
            "confidence": assessment.confidence,
            "recommended_transmission": assessment.recommended_transmission,
        }

    def get_status(self) -> dict[str, object]:
        return self.last_status

    def get_latest_frame(self) -> Optional[bytes]:
        return self.frame_store.get()


class DriverDashboardHandler(BaseHTTPRequestHandler):
    server_version = "NetraDriverDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path

        if path == "/":
            self._send_html()
            return

        if path == "/api/status":
            status = self.server.controller.get_status()
            body = json.dumps(status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/frame":
            frame = self.server.controller.get_latest_frame()
            if frame is None:
                self.send_response(204)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _send_html(self) -> None:
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8" />
            <title>NETRA AI Driver Monitor</title>
            <style>
                body {
                    margin: 0;
                    font-family: "Segoe UI", Arial, sans-serif;
                    background: radial-gradient(circle at top, #122233 0%, #091621 45%, #040b12 100%);
                    color: #f4f9ff;
                }
                .container {
                    max-width: 1400px;
                    margin: 24px auto;
                    padding: 20px 24px 32px;
                }
                .header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 16px;
                    margin-bottom: 22px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid rgba(160, 206, 255, 0.22);
                }
                .brand {
                    font-size: 12px;
                    letter-spacing: 0.18em;
                    text-transform: uppercase;
                    color: #7cd0ff;
                    margin-bottom: 6px;
                }
                .title-wrap {
                    display: flex;
                    align-items: center;
                    gap: 14px;
                }
                .logo-pill {
                    background: rgba(124, 208, 255, 0.12);
                    border: 1px solid rgba(124, 208, 255, 0.42);
                    color: #8ad9ff;
                    border-radius: 10px;
                    padding: 8px 12px;
                    font-size: 0.82rem;
                    font-weight: 700;
                    letter-spacing: 0.12em;
                    text-transform: uppercase;
                }
                h2 {
                    margin: 0;
                    font-weight: 700;
                    font-size: clamp(1.6rem, 3vw, 2.4rem);
                }
                .badge {
                    padding: 12px 20px;
                    border-radius: 999px;
                    font-size: 0.8rem;
                    font-weight: 800;
                    letter-spacing: 0.14em;
                    text-transform: uppercase;
                    background: rgba(22, 39, 59, 0.96);
                    border: 1px solid rgba(125, 180, 255, 0.55);
                    box-shadow: 0 0 20px rgba(76, 160, 255, 0.18);
                }
                .topbar {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 18px;
                    margin-bottom: 18px;
                    padding: 10px 14px 12px;
                    border-radius: 12px;
                    background: rgba(8, 18, 28, 0.85);
                    border: 1px solid rgba(150, 196, 255, 0.19);
                }
                .driver-meta {
                    display: flex;
                    gap: 18px;
                    flex-wrap: wrap;
                    color: #dfeeff;
                    font-size: 0.85rem;
                }
                .meta-pill {
                    padding: 8px 12px;
                    border-radius: 999px;
                    background: rgba(130, 180, 255, 0.08);
                    border: 1px solid rgba(130, 180, 255, 0.22);
                }
                .risk-high { background: rgba(220,53,69,0.18); border-color: #ff6674; color: #ffdfe5; }
                .risk-moderate { background: rgba(255,193,7,0.16); border-color: #ffc857; color: #ffecc0; }
                .risk-normal { background: rgba(25,135,84,0.18); border-color: #6fe8b3; color: #d8ffef; }
                .grid {
                    display: grid;
                    grid-template-columns: minmax(0, 2.3fr) minmax(280px, 0.9fr);
                    gap: 22px;
                }
                .panel {
                    background: rgba(10, 19, 29, 0.9);
                    border: 1px solid rgba(130, 180, 240, 0.26);
                    border-radius: 18px;
                    padding: 18px;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.3);
                }
                .feed {
                    width: 100%;
                    display: block;
                    border-radius: 16px;
                    background: #0b1723;
                    border: 1px solid rgba(103, 146, 203, 0.35);
                    min-height: 520px;
                    object-fit: cover;
                }
                .metrics {
                    display: grid;
                    gap: 12px;
                    margin-top: 18px;
                }
                .metric {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 14px;
                    border-radius: 12px;
                    background: rgba(97, 124, 177, 0.08);
                    border: 1px solid rgba(176, 203, 255, 0.12);
                    font-size: 0.96rem;
                }
                .metric strong {
                    color: #ffffff;
                    font-size: 1rem;
                }
                .status-window {
                    margin-top: 18px;
                    padding: 12px 14px;
                    border-radius: 12px;
                    background: rgba(13, 24, 37, 0.9);
                    border: 1px solid rgba(143, 176, 221, 0.18);
                }
                ul {
                    padding-left: 20px;
                    margin-top: 10px;
                    line-height: 1.7;
                    color: #ebf4ff;
                }
                .small {
                    font-size: 11px;
                    color: #9bb6d9;
                    text-transform: uppercase;
                    letter-spacing: 0.12em;
                }
                @media (max-width: 900px) {
                    .grid {
                        grid-template-columns: 1fr;
                    }
                    .feed {
                        min-height: 360px;
                    }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="title-wrap">
                        <div class="logo-pill">NETRA</div>
                        <div>
                            <div class="brand">Driver Intelligence Platform</div>
                            <h2>Driver Monitoring View</h2>
                        </div>
                    </div>
                    <div id="riskBadge" class="badge">Evaluating</div>
                </div>

                <div class="topbar">
                    <div class="driver-meta">
                        <div class="meta-pill">Driver ID: <strong id="driverId">drv_demo</strong></div>
                        <div class="meta-pill">Vehicle ID: <strong id="vehicleId">veh_demo</strong></div>
                        <div class="meta-pill">Live time: <strong id="clock">--:--:--</strong></div>
                    </div>
                </div>

                <div class="grid">
                    <div class="panel">
                        <img id="feedImage" class="feed" src="/api/frame" alt="Driver camera feed" />
                    </div>

                    <div class="panel">
                        <div class="small">AI Decision</div>
                        <div class="metrics">
                            <div class="metric"><span>Risk Level</span><strong id="riskLevel">--</strong></div>
                            <div class="metric"><span>Confidence</span><strong id="confidence">--</strong></div>
                            <div class="metric"><span>Transmission</span><strong id="transmission">--</strong></div>
                        </div>
                        <div class="status-window">
                            <div class="small">Reasons</div>
                            <ul id="reasons"></ul>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                async function refreshStatus() {
                    try {
                        const res = await fetch('/api/status');
                        const data = await res.json();
                        const risk = (data.risk_level || 'NORMAL').toUpperCase();
                        const badge = document.getElementById('riskBadge');
                        badge.textContent = risk;
                        badge.className = 'badge ' + (
                            risk === 'HIGH' ? 'risk-high' :
                            risk === 'MODERATE' ? 'risk-moderate' : 'risk-normal'
                        );

                        document.getElementById('driverId').textContent = 'drv_demo';
                        document.getElementById('vehicleId').textContent = 'veh_demo';
                        document.getElementById('riskLevel').textContent = risk;
                        document.getElementById('confidence').textContent = (data.confidence ?? 0).toString();
                        document.getElementById('transmission').textContent = (data.recommended_transmission || 'cloud').toUpperCase();

                        const reasons = document.getElementById('reasons');
                        reasons.innerHTML = '';
                        for (const reason of (data.reasons || [])) {
                            const li = document.createElement('li');
                            li.textContent = reason;
                            reasons.appendChild(li);
                        }
                    } catch (err) {
                        console.error(err);
                    }
                }

                function updateClock() {
                    const now = new Date();
                    const timeText = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    document.getElementById('clock').textContent = timeText;
                }

                function refreshFrame() {
                    const img = document.getElementById('feedImage');
                    const ts = new Date().getTime();
                    img.src = '/api/frame?ts=' + ts;
                }

                refreshStatus();
                updateClock();
                refreshFrame();
                setInterval(refreshStatus, 1000);
                setInterval(updateClock, 1000);
                setInterval(refreshFrame, 500);
            </script>
        </body>
        </html>
        """
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DriverDashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], controller: DriverAIController) -> None:
        super().__init__(server_address, handler_cls)
        self.controller = controller


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NETRA AI driver monitoring dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--drowsiness-score", type=float, default=0.82)
    parser.add_argument("--distraction-score", type=float, default=0.74)
    parser.add_argument("--yawning-score", type=float, default=0.6)
    parser.add_argument("--phone-usage-score", type=float, default=0.2)
    parser.add_argument("--speed-kph", type=float, default=82.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    controller = DriverAIController(
        camera_index=args.camera_index,
        drowsiness_score=args.drowsiness_score,
        distraction_score=args.distraction_score,
        yawning_score=args.yawning_score,
        phone_usage_score=args.phone_usage_score,
        speed_kph=args.speed_kph,
    )
    controller.start()

    server = DriverDashboardServer((args.host, args.port), DriverDashboardHandler, controller)
    print(f"NETRA AI dashboard is running on http://{args.host}:{args.port}/")
    print("Open the page in your browser to view the live driver monitoring dashboard.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
