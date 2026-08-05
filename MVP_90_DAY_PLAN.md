# Fleet Management SaaS MVP Plan (90 Days)

## Week 1 to 3: Core Data Services
- Vehicle CRUD API: make, model, license plate.
- Driver CRUD API: license and contact profile.
- Basic input validation and error handling.
- API smoke and unit tests.

Implemented starter:
- fleet_mvp_api.py
- tests/test_fleet_mvp_api.py

## Week 4 to 6: Live KPI Dashboard Backend
- KPI endpoint for fleet size, active drivers, budget threshold alerts.
- Telemetry ingestion endpoint with live GPS coordinates.
- Prepare websocket or polling strategy for dashboard refresh.

Implemented starter:
- /api/telemetry/events
- /api/kpi/widgets

## Week 7 to 9: Safety Analytics
- Driver safety scorecards from behavioral telemetry.
- Drowsiness and distraction trend counters.
- Threshold-based escalations and review queues.

Implemented starter:
- /api/safety/scorecards

## Week 10 to 13: Hardening and Pilot Readiness
- Authentication and role-based access control.
- Persistent database and migrations.
- Audit log retention policy.
- Pilot customer demo scripts and observability alerts.

## MVP Definition of Done
- CRUD operations complete and tested.
- Dashboard APIs serve real-time KPI payloads.
- Safety scorecard endpoint operational.
- SIL suite green on main branch.
- HIL smoke pass on bench setup.
