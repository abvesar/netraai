# PostgreSQL and RBAC Setup

## 1) Configure PostgreSQL connection

Set DATABASE_URL before starting the API.

PowerShell example:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://netra_user:netra_pass@localhost:5432/netra_fleet"
```

If DATABASE_URL is not set, the API uses SQLite at artifacts/fleet_mvp.db.

## 2) Apply schema migrations

```powershell
.\.venv\Scripts\python.exe .\db_migrate.py --database-url $env:DATABASE_URL
```

Migration files:
- migrations/0001_init.sql

## 3) Configure API key role mapping

Set NETRA_API_KEYS_JSON with key-to-role map.

```powershell
$env:NETRA_API_KEYS_JSON='{"viewer_prod_key":"viewer","ops_prod_key":"operator","admin_prod_key":"admin"}'
```

Roles:
- viewer: read-only endpoints
- operator: create/update + telemetry ingest
- admin: delete endpoints + operator privileges

## 4) Start API

```powershell
.\.venv\Scripts\python.exe .\fleet_mvp_api.py
```

Default port: 6060

## 5) Example request

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:6060/api/vehicles -Headers @{"X-API-Key"="viewer_prod_key"}
```
