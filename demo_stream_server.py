import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[bytes] = None
        self._updated_at = 0.0

    def set(self, frame: bytes) -> None:
        with self._lock:
            self._frame = frame
            self._updated_at = time.time()

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._frame

    def age_seconds(self) -> float:
        with self._lock:
            if self._frame is None:
                return float("inf")
            return time.time() - self._updated_at


class DemoCameraHandler(BaseHTTPRequestHandler):
    server_version = "NetraDemoStream/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json({"status": "ok"})
            return

        if self.path == "/latest":
            frame = self.server.frame_store.get()
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

        if self.path == "/feed":
            self._stream_mjpeg()
            return

        if self.path == "/":
            html = """
            <html>
              <body>
                <h2>NETRA AI Demo Camera Stream</h2>
                <img src="/feed" width="640" height="480" />
              </body>
            </html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/upload":
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            if not payload:
                self._send_json({"status": "error", "message": "empty payload"}, 400)
                return

            self.server.frame_store.set(payload)
            self._send_json({"status": "ok", "bytes_received": len(payload)})
            return

        self.send_response(404)
        self.end_headers()

    def _stream_mjpeg(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()

        while True:
            frame = self.server.frame_store.get()
            if frame is None:
                time.sleep(0.1)
                continue

            boundary = b"--frame\r\n"
            header = (
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
            )
            try:
                self.wfile.write(boundary)
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            except Exception:
                break
            time.sleep(0.1)

    def _send_json(self, payload: dict, status_code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


class DemoStreamServer(ThreadingHTTPServer):
    def __init__(self, server_address: Tuple[str, int], handler_cls: Type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, handler_cls)
        self.frame_store = FrameStore()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Demo cloud/server for remote webcam feed testing")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = DemoStreamServer((args.host, args.port), DemoCameraHandler)
    print(f"NETRA AI demo server listening on http://{args.host}:{args.port}")
    print("Use POST /upload with JPEG bytes from the remote laptop")
    print("Open http://<your-laptop-ip>:9000/ to view the stream")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
