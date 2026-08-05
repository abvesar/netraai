from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from enum import IntEnum

try:
    import can
except Exception as exc:
    raise RuntimeError("python-can is required. Install with: pip install python-can") from exc


ENGINE_STATUS_ID = 0x102
ENGINE_START_REQUEST_ID = 0x100


class EngineStatus(IntEnum):
    STOPPED = 0
    RUNNING = 1
    START_REQUESTED = 2
    START_BLOCKED = 3


@dataclass(frozen=True)
class TruckConfig:
    interface: str = "virtual"
    channel: str = "vcan0"
    node_id: int = 1
    status_interval_seconds: float = 1.0
    request_interval_seconds: float = 3.0
    cycles: int = 10


class VirtualTruck:
    def __init__(self, config: TruckConfig) -> None:
        self.config = config
        self.bus = can.Bus(interface=config.interface, channel=config.channel, receive_own_messages=True)
        self.status = EngineStatus.STOPPED

    def send_status(self, status: EngineStatus) -> None:
        payload = bytes([int(status), self.config.node_id & 0xFF, 0, 0, 0, 0, 0, 0])
        msg = can.Message(arbitration_id=ENGINE_STATUS_ID, data=payload, is_extended_id=False)
        self.bus.send(msg)
        print(f"truck_tx id=0x{ENGINE_STATUS_ID:03X} status={status.name} data={msg.data.hex()}")

    def send_start_request(self) -> None:
        msg = can.Message(
            arbitration_id=ENGINE_START_REQUEST_ID,
            data=bytes([1, self.config.node_id & 0xFF, 0, 0, 0, 0, 0, 0]),
            is_extended_id=False,
        )
        self.bus.send(msg)
        print(f"truck_tx id=0x{ENGINE_START_REQUEST_ID:03X} start_request=1 data={msg.data.hex()}")

    def run(self) -> int:
        last_status = 0.0
        last_request = 0.0
        requests_sent = 0

        while requests_sent < self.config.cycles:
            now = time.time()

            if now - last_status >= self.config.status_interval_seconds:
                self.send_status(self.status)
                last_status = now

            if now - last_request >= self.config.request_interval_seconds:
                self.status = EngineStatus.START_REQUESTED
                self.send_status(self.status)
                self.send_start_request()
                last_request = now
                requests_sent += 1

            time.sleep(0.05)

        return 0

    def close(self) -> None:
        self.bus.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Virtual Truck CAN status simulator")
    parser.add_argument("--interface", default="virtual", help="python-can interface (virtual/socketcan)")
    parser.add_argument("--channel", default="vcan0", help="CAN channel")
    parser.add_argument("--node-id", type=int, default=1, help="Truck node id")
    parser.add_argument("--status-interval", type=float, default=1.0, help="Engine status publish interval")
    parser.add_argument("--request-interval", type=float, default=3.0, help="Start request interval")
    parser.add_argument("--cycles", type=int, default=10, help="Number of start request cycles")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = TruckConfig(
        interface=args.interface,
        channel=args.channel,
        node_id=args.node_id,
        status_interval_seconds=max(0.1, args.status_interval),
        request_interval_seconds=max(0.2, args.request_interval),
        cycles=max(1, args.cycles),
    )

    truck = VirtualTruck(config)
    try:
        return truck.run()
    finally:
        truck.close()


if __name__ == "__main__":
    raise SystemExit(main())
