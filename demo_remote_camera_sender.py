import argparse
import time
from pathlib import Path
from typing import Optional

import requests


class RemoteCameraSender:
    def __init__(self, camera_url: str, upload_url: str, interval_seconds: float = 0.5) -> None:
        self.camera_url = camera_url
        self.upload_url = upload_url
        self.interval_seconds = interval_seconds

    def send_frames(self, limit: Optional[int] = None) -> int:
        count = 0
        while limit is None or count < limit:
            response = requests.get(self.camera_url, timeout=10)
            response.raise_for_status()
            upload = requests.post(self.upload_url, data=response.content, timeout=10)
            upload.raise_for_status()
            count += 1
            print(f"sent_frame={count} bytes={len(response.content)} status={upload.status_code}")
            time.sleep(self.interval_seconds)
        return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Demo sender for remote laptop webcam to DRISHTI AI demo server")
    parser.add_argument("--camera-url", required=True, help="URL of the remote webcam snapshot endpoint")
    parser.add_argument("--upload-url", default="http://localhost:9000/upload", help="Demo server upload endpoint")
    parser.add_argument("--interval-seconds", type=float, default=0.5, help="How often to send frames")
    parser.add_argument("--limit", type=int, default=20, help="Number of frames to send; 0 or negative means forever")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sender = RemoteCameraSender(
        camera_url=args.camera_url,
        upload_url=args.upload_url,
        interval_seconds=args.interval_seconds,
    )
    limit = None if args.limit <= 0 else args.limit
    sender.send_frames(limit=limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
