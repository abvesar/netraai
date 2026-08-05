from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ValidationResult:
    name: str
    command: List[str]
    exit_code: int
    duration_ms: int
    output_tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def run_step(name: str, command: List[str]) -> ValidationResult:
    started = time.time()
    proc = subprocess.run(command, capture_output=True, text=True)
    ended = time.time()

    output = (proc.stdout or "") + (proc.stderr or "")
    tail = output[-2500:]

    duration_ms = int((ended - started) * 1000)
    print(f"step={name} exit={proc.returncode} duration_ms={duration_ms}")
    return ValidationResult(
        name=name,
        command=command,
        exit_code=proc.returncode,
        duration_ms=duration_ms,
        output_tail=tail,
    )


def run_sil() -> List[ValidationResult]:
    py = sys.executable
    return [
        run_step(
            "unit_tests",
            [py, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        ),
        run_step(
            "scenario_allow",
            [
                py,
                "integrated_scenario_runner.py",
                "--requests",
                "2",
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
            ],
        ),
        run_step(
            "scenario_deny",
            [
                py,
                "integrated_scenario_runner.py",
                "--requests",
                "2",
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
            ],
        ),
    ]


def run_hil(hil_command: str) -> List[ValidationResult]:
    if hil_command:
        return [run_step("hil_bench", ["powershell", "-NoProfile", "-Command", hil_command])]

    py = sys.executable
    return [run_step("hil_bench", [py, "hil_bench_runner.py", "--simulated"])]


def write_report(results: List[ValidationResult], report_file: Path) -> int:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_epoch_s": time.time(),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [
            {
                "name": r.name,
                "command": r.command,
                "exit_code": r.exit_code,
                "duration_ms": r.duration_ms,
                "output_tail": r.output_tail,
                "passed": r.passed,
            }
            for r in results
        ],
    }
    report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"report_file={report_file} passed={payload['passed']} failed={payload['failed']}")

    if payload["failed"] > 0:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Left-shift validation orchestrator (SIL + HIL hook)")
    parser.add_argument("--mode", choices=["sil", "hil"], default="sil")
    parser.add_argument("--hil-command", default="", help="Bench command for HIL execution")
    parser.add_argument("--report-file", default="artifacts/validation_report.json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report_file = Path(args.report_file)

    if args.mode == "sil":
        results = run_sil()
        return write_report(results, report_file)

    results = run_hil(args.hil_command)
    return write_report(results, report_file)


if __name__ == "__main__":
    raise SystemExit(main())
