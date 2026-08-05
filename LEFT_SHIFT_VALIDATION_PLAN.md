# Left-Shift Validation Plan (SIL and HIL)

## Objective
Catch safety-critical defects early, before expensive hardware and field trials.

## SIL Track (Immediate)

Scope:
- Safety decision policy logic.
- Edge gatekeeper loop behavior.
- CAN override and intervention scenario outcomes.

Execution:
1. Unit tests:
   - tests/test_safety_core.py
   - tests/test_security_loop_sim.py
   - tests/test_fleet_mvp_api.py
2. Integrated scenarios:
   - integrated_scenario_runner.py allow case
   - integrated_scenario_runner.py deny case
3. Orchestration command:

```powershell
.\.venv\Scripts\python.exe .\validation_orchestrator.py --mode sil --report-file artifacts/validation_report.json
```

Pass Criteria:
- All unit tests pass.
- Allow scenario produces relay ON and no intervention.
- Deny scenario produces relay OFF and intervention events.

## HIL Track (Bridge to Real Hardware)

Bench Topology:
- Edge controller: Raspberry Pi CM4 (or target ECU dev board).
- Real relay module and MQ-3 front-end circuit.
- CAN transceiver + bus simulator node.
- Camera endpoint reachable over isolated test network.

Execution Pattern:
- Use validation_orchestrator HIL hook to run your bench command:

```powershell
.\.venv\Scripts\python.exe .\validation_orchestrator.py --mode hil --hil-command "python your_hil_bench_runner.py" --report-file artifacts/hil_report.json
```

HIL Entry Criteria:
- SIL pass in latest commit.
- Calibration and threshold files configured.
- Power, GPIO polarity, and relay-safe default verified.

HIL Exit Criteria:
- Start request blocked within expected timing when alcohol violation is simulated.
- Start request allowed when simulated sobriety and facial verification are valid.
- Camera intervention triggers on deny path and logs traceability events.

## Defect Triage Policy
- Safety critical: fix before merge.
- Functional: assign owner and due date in sprint.
- Cosmetic: backlog unless safety impact exists.

## Artifacts
- SIL report: artifacts/validation_report.json
- HIL report: artifacts/hil_report.json
- Decision audit: artifacts/gatekeeper_events.jsonl
