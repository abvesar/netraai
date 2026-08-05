from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth


@dataclass(frozen=True)
class HikvisionIsapiConfig:
    base_url: str
    username: str
    password: str
    timeout_seconds: float = 8.0
    verify_tls: bool = True
    dry_run: bool = True


@dataclass(frozen=True)
class IsapiEndpoints:
    # Common still-image endpoint for many Hikvision models.
    snapshot_path: str = "/ISAPI/Streaming/channels/101/picture"
    # Model-dependent endpoint for IO output trigger.
    alarm_output_template: str = "/ISAPI/System/IO/outputs/{output_id}/trigger"
    # Model-dependent endpoint for audio output/broadcast.
    audio_broadcast_path: str = "/ISAPI/AccessControl/EventCardLinkageCfg/AudioOut"


class HikvisionIsapiClient:
    def __init__(self, config: HikvisionIsapiConfig, endpoints: Optional[IsapiEndpoints] = None) -> None:
        self.config = config
        self.endpoints = endpoints or IsapiEndpoints()
        self._session = requests.Session()
        self._session.auth = HTTPDigestAuth(self.config.username, self.config.password)

    def get_live_frame(self, output_file: Optional[str] = None) -> bytes:
        url = self._build_url(self.endpoints.snapshot_path)
        if self.config.dry_run:
            print(f"DRY_RUN GET {url}")
            data = b"SIMULATED_FRAME"
        else:
            response = self._session.get(
                url,
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_tls,
            )
            response.raise_for_status()
            data = response.content

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        return data

    def trigger_alarm_output(self, output_id: int = 1, active: bool = True) -> int:
        path = self.endpoints.alarm_output_template.format(output_id=output_id)
        url = self._build_url(path)
        state = "high" if active else "low"
        payload = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<IOPortData>"
            f"<outputState>{state}</outputState>"
            "</IOPortData>"
        )

        if self.config.dry_run:
            print(f"DRY_RUN PUT {url} state={state}")
            return 200

        response = self._session.put(
            url,
            data=payload,
            headers={"Content-Type": "application/xml"},
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()
        return response.status_code

    def speak_text(self, text: str, repeat: int = 1) -> int:
        url = self._build_url(self.endpoints.audio_broadcast_path)
        payload = {
            "AudioOut": {
                "enabled": True,
                "repeatTimes": repeat,
                "text": text,
            }
        }

        if self.config.dry_run:
            print(f"DRY_RUN PUT {url} text={text!r} repeat={repeat}")
            return 200

        response = self._session.put(
            url,
            json=payload,
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()
        return response.status_code

    def post_custom(self, path: str, payload: str, content_type: str = "application/xml") -> int:
        url = self._build_url(path)
        if self.config.dry_run:
            print(f"DRY_RUN POST {url} content_type={content_type}")
            return 200

        response = self._session.post(
            url,
            data=payload,
            headers={"Content-Type": content_type},
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
        )
        response.raise_for_status()
        return response.status_code

    def _build_url(self, path: str) -> str:
        normalized_base = self.config.base_url.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{normalized_base}{normalized_path}"
