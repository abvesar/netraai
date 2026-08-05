from __future__ import annotations

import argparse
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityLoopConfig:
    sobriety_ok: bool
    facial_ok: bool
    cycles: int = 1
    cycle_seconds: float = 0.5


class SimulatedRelay:
    """Relay abstraction where CLOSED means ignition unlocked."""

    def __init__(self) -> None:
        self.closed = False
        self.open()

    def close(self) -> None:
        self.closed = True
        print("relay_state=CLOSED ignition=UNLOCKED")

    def open(self) -> None:
        self.closed = False
        print("relay_state=OPEN ignition=LOCKED")


class SecurityLoop:
    """Core rule: unlock only when sobriety and facial verification are both true."""

    def __init__(self, relay: SimulatedRelay, config: SecurityLoopConfig) -> None:
        self.relay = relay
        self.config = config

    def evaluate_once(self) -> bool:
        if self.config.sobriety_ok and self.config.facial_ok:
            self.relay.close()
            print("decision=ALLOW reasons=all_checks_passed")
            return True

        self.relay.open()
        reasons: list[str] = []
        if not self.config.sobriety_ok:
            reasons.append("sobriety_failed")
        if not self.config.facial_ok:
            reasons.append("facial_verification_failed")
        print(f"decision=DENY reasons={','.join(reasons)}")
        return False

    def run(self) -> int:
        remaining = max(1, self.config.cycles)
        while remaining > 0:
            self.evaluate_once()
            remaining -= 1
            if remaining > 0:
                time.sleep(max(0.05, self.config.cycle_seconds))
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Security loop simulator")
    parser.add_argument("--sobriety-ok", action="store_true", help="Simulated sobriety check passed")
    parser.add_argument("--facial-ok", action="store_true", help="Simulated facial verification passed")
    parser.add_argument("--cycles", type=int, default=1, help="Loop cycles")
    parser.add_argument("--cycle-seconds", type=float, default=0.5, help="Loop period seconds")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = SecurityLoopConfig(
        sobriety_ok=args.sobriety_ok,
        facial_ok=args.facial_ok,
        cycles=args.cycles,
        cycle_seconds=args.cycle_seconds,
    )
    relay = SimulatedRelay()
    loop = SecurityLoop(relay=relay, config=config)
    return loop.run()


if __name__ == "__main__":
    raise SystemExit(main())
