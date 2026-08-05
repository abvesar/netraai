from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List

import requests
from flask import Flask, Response, jsonify, render_template_string, request


HTML_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NetraAI Camera Monitor</title>
  <style>
    body { font-family: Segoe UI, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 20px; }
    .panel { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    h1 { margin-top: 0; font-size: 24px; }
    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
    img { width: 100%; border-radius: 10px; border: 1px solid #334155; background: #020617; }
    pre { max-height: 420px; overflow: auto; background: #020617; padding: 12px; border-radius: 8px; border: 1px solid #334155; }
    .meta { font-size: 13px; color: #94a3b8; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>NetraAI Remote Camera + Webhook Receiver</h1>
    <div class="panel meta">
      Camera URL: <span id="camUrl"></span><br/>
      Webhook endpoint (for test scripts): <strong>/webhook</strong>
    </div>

    <div class="grid">
      <div class="panel">
        <h3>Live Feed (from remote laptop camera)</h3>
        <img id="feed" src="/snapshot_proxy" alt="Live camera feed" />
      </div>
      <div class="panel">
        <h3>Incoming Webhook Events</h3>
        <pre id="events">[]</pre>
      </div>
    </div>
  </div>

<script>
const feed = document.getElementById('feed');
const eventsBox = document.getElementById('events');
const camUrl = document.getElementById('camUrl');
camUrl.textContent = {{ camera_url|tojson }};

setInterval(() => {
  feed.src = '/snapshot_proxy?t=' + Date.now();
}, {{ refresh_ms }});

async function refreshEvents() {
  try {
    const res = await fetch('/events');
    const data = await res.json();
    eventsBox.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    eventsBox.textContent = 'Failed to load events: ' + err;
  }
}
setInterval(refreshEvents, 1000);
refreshEvents();
</script>
</body>
</html>
"""


@dataclass(frozen=True)
class ServerConfig:
    camera_url: str
    host: str = "0.0.0.0"
    port: int = 5050
    refresh_ms: int = 700
    request_timeout_seconds: float = 5.0
    max_events: int = 200


def create_app(config: ServerConfig) -> Flask:
    app = Flask(__name__)
    events: Deque[Dict[str, object]] = deque(maxlen=config.max_events)
    lock = threading.Lock()

    @app.get("/")
    def index() -> str:
        return render_template_string(
            HTML_PAGE,
            camera_url=config.camera_url,
            refresh_ms=max(250, config.refresh_ms),
        )

    @app.post("/webhook")
    def webhook() -> Response:
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {"raw": request.data.decode("utf-8", errors="replace")}

        event = {
            "timestamp": int(time.time()),
            "remote_addr": request.remote_addr,
            "payload": payload,
        }
        with lock:
            events.appendleft(event)

        return jsonify({"status": "ok"})

    @app.get("/events")
    def get_events() -> Response:
        with lock:
            snapshot: List[Dict[str, object]] = list(events)
        return Response(json.dumps(snapshot, indent=2), mimetype="application/json")

    @app.get("/snapshot_proxy")
    def snapshot_proxy() -> Response:
        try:
            resp = requests.get(config.camera_url, timeout=config.request_timeout_seconds)
            resp.raise_for_status()
        except Exception as exc:
            return Response(f"Camera fetch failed: {exc}", status=502, mimetype="text/plain")

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return Response(resp.content, mimetype=content_type)

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local webhook receiver + remote camera viewer")
    parser.add_argument(
        "--camera-url",
        required=True,
        help="Remote laptop webcam URL, e.g. http://192.168.1.20:8080/shot.jpg",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Listen host")
    parser.add_argument("--port", type=int, default=5050, help="Listen port")
    parser.add_argument("--refresh-ms", type=int, default=700, help="UI refresh interval for feed")
    parser.add_argument("--timeout", type=float, default=5.0, help="Snapshot fetch timeout")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = ServerConfig(
        camera_url=args.camera_url,
        host=args.host,
        port=args.port,
        refresh_ms=args.refresh_ms,
        request_timeout_seconds=args.timeout,
    )

    app = create_app(config)
    app.run(host=config.host, port=config.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
