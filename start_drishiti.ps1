$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $workspace ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Python venv not found at: $python"
    exit 1
}

& $python "fleet_gatekeeper_hub.py" --driver-id drv_001 --vehicle-id veh_001 --drowsiness-score 0.82 --distraction-score 0.74 --yawning-score 0.2 --phone-usage-score 0.1 --speed-kph 82 --max-cycles 1 --transmission-mode cloud
exit $LASTEXITCODE
