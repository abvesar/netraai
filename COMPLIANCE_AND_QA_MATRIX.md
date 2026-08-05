# Compliance and QA Matrix

## Coding Standards (MISRA Intent Alignment)
- Deterministic decisions in safety_core.py.
- Fail-safe defaults in gatekeeper and immobilizer paths.
- Explicit reason codes for every deny condition.
- Port and adapter separation in fleet_gatekeeper_hub.py.

## Functional Safety Preparation (ISO 26262 Direction)
- Hazard focus: unintended engine enable.
- Safety goal: deny start on uncertain or unsafe inputs.
- Traceability: decision logs and validation reports in artifacts.
- Verification: unit tests plus integrated scenario validation.

## Cybersecurity Preparation (ISO/SAE 21434 Direction)
- Protect camera and API credentials outside source code.
- Enforce TLS for hub and camera transport in production.
- Restrict CAN and control services to segmented trusted networks.
- Add integrity checks and secure boot on edge hardware.

## Process Maturity (ASPICE Level 2 Direction)
- Requirements-to-test linkage in plan documents.
- Repeatable CI safety gates via .github/workflows/safety-ci.yml.
- Defect triage policy with ownership and closure evidence.
- Release checklist requiring SIL/HIL evidence.

## Required Next Controls
- Threat model and attack surface register.
- SBOM generation in CI.
- Secret scanning and dependency vulnerability scanning.
- Signed release artifacts and rollback procedures.
