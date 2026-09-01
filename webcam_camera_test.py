import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Type

import requests


@dataclass(frozen=True)
class WebcamTestConfig:
    camera_url: str
    mode: str = "snapshot"
    output_file: str = "artifacts/webcam_frame.jpg"
    timeout_seconds: float = 8.0
    webhook_url: Optional[str] = None
    dry_run_webhook: bool = True


class WebcamNetworkCameraClient:
    """Camera test client for a webcam exposed on the local network.

    Expected source examples:
    - Snapshot endpoint: http://192.168.1.20:8080/shot.jpg
    - Stream endpoint: http://192.168.1.20:8080/video (requires opencv-python)
    """

    def __init__(self, config: WebcamTestConfig) -> None:
        self.config = config

    def get_live_frame(self, output_file: Optional[str] = None) -> bytes:
        if self.config.mode == "snapshot":
            data = self._get_snapshot_bytes()
        elif self.config.mode == "stream":
            data = self._get_stream_frame_bytes()
        else:
            raise ValueError(f"Unsupported mode: {self.config.mode}")

        target = output_file or self.config.output_file
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data

    def trigger_alarm_output(self, active: bool = True) -> int:
        payload = {"event": "alarm_output", "active": active}
        return self._post_webhook(payload)

    def speak_text(self, text: str, repeat: int = 1) -> int:
        payload = {"event": "audio_announcement", "text": text, "repeat": repeat}
        return self._post_webhook(payload)

    def _get_snapshot_bytes(self) -> bytes:
        response = requests.get(self.config.camera_url, timeout=self.config.timeout_seconds)
        response.raise_for_status()
        return response.content

    def _get_stream_frame_bytes(self) -> bytes:
        try:
            import cv2  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(
                "Stream mode requires opencv-python. Install with: pip install opencv-python"
            ) from exc

        capture = cv2.VideoCapture(self.config.camera_url)
        try:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("Unable to read frame from stream URL")

            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                raise RuntimeError("Unable to encode frame as JPEG")

            return encoded.tobytes()
        finally:
            capture.release()

    def _post_webhook(self, payload: Dict[str, object]) -> int:
        if not self.config.webhook_url:
            print(f"WEBHOOK_SKIPPED payload={payload}")
            return 200

        if self.config.dry_run_webhook:
            print(f"WEBHOOK_DRY_RUN url={self.config.webhook_url} payload={payload}")
            return 200

        response = requests.post(
            self.config.webhook_url,
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.status_code


def simple_facial_verification(frame_bytes: bytes, min_frame_bytes: int) -> bool:
    """Network-test stub: verifies we received a non-trivial image payload."""
    return len(frame_bytes) >= min_frame_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test camera functions using network webcam")
    parser.add_argument("--camera-url", required=True, help="Network webcam URL")
    parser.add_argument(
        "--mode",
        choices=["snapshot", "stream"],
        default="snapshot",
        help="snapshot for image URL, stream for MJPEG/RTSP-like URL",
    )
    parser.add_argument("--output-file", default="artifacts/webcam_frame.jpg", help="Saved frame path")
    parser.add_argument("--timeout-seconds", type=float, default=8.0, help="HTTP/stream timeout")
    parser.add_argument("--webhook-url", default="", help="Optional webhook to receive intervention events")
    parser.add_argument("--dry-run-webhook", action="store_true", help="Do not send real webhook requests")
    parser.add_argument(
        "--min-frame-bytes",
        type=int,
        default=1024,
        help="Minimum image payload bytes to mark facial verification as passed",
    )
    parser.add_argument(
        "--force-face-fail",
        action="store_true",
        help="Force failed facial verification to test alarm/audio paths",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    client = WebcamNetworkCameraClient(
        WebcamTestConfig(
            camera_url=args.camera_url,
            mode=args.mode,
            output_file=args.output_file,
            timeout_seconds=args.timeout_seconds,
            webhook_url=args.webhook_url or None,
            dry_run_webhook=args.dry_run_webhook,
        )
    )

    frame = client.get_live_frame()
    print(f"frame_bytes={len(frame)} saved={args.output_file}")

    if args.force_face_fail:
        facial_verified = False
    else:
        facial_verified = simple_facial_verification(
            frame_bytes=frame,
            min_frame_bytes=max(1, args.min_frame_bytes),
        )

    print(f"facial_verified={facial_verified}")

    if facial_verified:
        print("intervention=none")
        return 0

    client.trigger_alarm_output(active=True)
    client.speak_text(text="Facial verification failed. Please retry breath test.", repeat=1)
    print("intervention=alarm_and_audio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
