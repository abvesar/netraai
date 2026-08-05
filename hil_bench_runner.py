from __future__ import annotations

import argparse
import subprocess
import sys


def _run(command: list[str]) -> tuple[int, str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def run_simulated_hil() -> int:
    py = sys.executable
    allow_cmd = [
        py,
        "integrated_scenario_runner.py",
        "--requests",
        "1",
        "--request-interval",
        "0.2",
        "--status-interval",
        "0.2",
        "--mock-voltage",
        "1.20",
        "--clean-air-voltage",
        "1.00",
        "--threshold-brac",
        "0.02",
        "--brac-per-volt-delta",
        "0.04",
    ]
    deny_cmd = [
        py,
        "integrated_scenario_runner.py",
        "--requests",
        "1",
        "--request-interval",
        "0.2",
        "--status-interval",
        "0.2",
        "--mock-voltage",
        "1.60",
        "--clean-air-voltage",
        "1.00",
        "--threshold-brac",
        "0.02",
        "--brac-per-volt-delta",
        "0.04",
    ]

    allow_code, allow_out = _run(allow_cmd)
    print("hil_phase=allow exit=", allow_code)
    if allow_code != 0 or "decision=ALLOW" not in allow_out:
        print("hil_failure=allow_path")
        return 1

    deny_code, deny_out = _run(deny_cmd)
    print("hil_phase=deny exit=", deny_code)
    if deny_code != 0 or "decision=DENY" not in deny_out or "hub_intervention action=alarm_audio_snapshot" not in deny_out:
        print("hil_failure=deny_path")
        return 1

    print("hil_result=pass simulated=true")
    return 0


def run_external(command: str) -> int:
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True)
    print((proc.stdout or "")[-3000:])
    print((proc.stderr or "")[-1000:])
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HIL bench runner")
    parser.add_argument("--simulated", action="store_true", help="Run simulated HIL sequence")
    parser.add_argument("--bench-command", default="", help="Run external bench command in PowerShell")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.simulated:
        return run_simulated_hil()

    if not args.bench_command:
        print("error=missing_bench_command")
        return 2

    return run_external(args.bench_command)


if __name__ == "__main__":
    raise SystemExit(main())
