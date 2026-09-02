import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

latest_status = {
    "driver_id": "drv_001",
    "status": "WAITING",
    "drowsy": False,
    "distracted": False,
    "yawning": False,
    "fatigue_score": 0.0,
    "risk_level": "NORMAL",
    "timestamp": None,
}


@app.post("/api/driver-status")
def driver_status():
    data = request.get_json(force=True, silent=True) or {}
    if not data:
        return jsonify({"ok": False, "error": "No JSON payload provided"}), 400

    latest_status.update(
        {
            "driver_id": data.get("driver_id", latest_status["driver_id"]),
            "status": data.get("status", latest_status["status"]),
            "drowsy": bool(data.get("drowsy", False)),
            "distracted": bool(data.get("distracted", False)),
            "yawning": bool(data.get("yawning", False)),
            "fatigue_score": float(data.get("fatigue_score", 0.0) or 0.0),
            "risk_level": data.get("risk_level", latest_status["risk_level"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return jsonify({"ok": True, "status": latest_status})


@app.get("/api/current")
def current_status():
    return jsonify(latest_status)


@app.get("/")
def index():
    return render_template_string(
        """
        <html>
        <head>
            <title>DRISHTI AI Remote Dashboard</title>
            <style>
                body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }
                .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; max-width: 1200px; margin: 0 auto; }
                .panel { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
                h1, h2 { color: #7dd3fc; margin-top: 0; }
                .badge { display: inline-block; background: #22c55e; color: #052e16; padding: 6px 12px; border-radius: 999px; font-weight: 700; }
                .badge.high { background: #ef4444; color: white; }
                .badge.moderate { background: #f59e0b; color: #1f2937; }
                .metric { font-size: 18px; margin: 10px 0; }
                .label { color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
                .value { font-size: 30px; font-weight: 700; }
                .status-line { margin-top: 12px; font-size: 18px; }
                .alert { color: #fca5a5; }
            </style>
        </head>
        <body>
            <div class="grid">
                <div class="panel">
                    <h1>DRISHTI AI</h1>
                    <div id="statusBadge" class="badge">NORMAL</div>
                    <div class="status-line" id="statusText">Waiting for a live driver signal...</div>
                    <div class="metric"><span class="label">Driver ID</span><br><span id="driverId">drv_001</span></div>
                    <div class="metric"><span class="label">Fatigue Score</span><br><span id="fatigueScore">0.00</span></div>
                    <div class="metric"><span class="label">Last Updated</span><br><span id="timestamp">-</span></div>
                </div>
                <div class="panel">
                    <h2>Alert States</h2>
                    <div class="metric"><span class="label">Drowsy</span><br><span id="drowsy">False</span></div>
                    <div class="metric"><span class="label">Distracted</span><br><span id="distracted">False</span></div>
                    <div class="metric"><span class="label">Yawning</span><br><span id="yawning">False</span></div>
                    <div class="metric"><span class="label">Risk Level</span><br><span id="riskLevel">NORMAL</span></div>
                </div>
            </div>
            <script>
                async function refresh() {
                    const res = await fetch('/api/current');
                    const data = await res.json();
                    const badge = document.getElementById('statusBadge');
                    const statusText = document.getElementById('statusText');
                    badge.textContent = data.risk_level || 'NORMAL';
                    badge.className = 'badge';
                    if ((data.risk_level || '').toUpperCase() === 'HIGH') badge.classList.add('high');
                    else if ((data.risk_level || '').toUpperCase() === 'MODERATE') badge.classList.add('moderate');

                    document.getElementById('driverId').textContent = data.driver_id || 'drv_001';
                    document.getElementById('fatigueScore').textContent = Number(data.fatigue_score || 0).toFixed(2);
                    document.getElementById('timestamp').textContent = data.timestamp || '-';
                    document.getElementById('drowsy').textContent = String(Boolean(data.drowsy));
                    document.getElementById('distracted').textContent = String(Boolean(data.distracted));
                    document.getElementById('yawning').textContent = String(Boolean(data.yawning));
                    document.getElementById('riskLevel').textContent = data.risk_level || 'NORMAL';

                    if (data.drowsy || data.distracted || data.yawning) {
                        statusText.textContent = 'Driver alert active';
                        statusText.classList.add('alert');
                    } else {
                        statusText.textContent = 'Driver is within acceptable monitoring range';
                        statusText.classList.remove('alert');
                    }
                }
                setInterval(refresh, 2000);
                refresh();
            </script>
        </body>
        </html>
        """
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
