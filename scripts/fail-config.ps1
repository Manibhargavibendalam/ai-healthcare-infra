# FAILURE 7 (inject): bad configuration. Worker gets an unreachable EHR_URL
# via a temporary override file. Expected SAFE failure: no crash, no loss —
# jobs retry with 'EHR connection failed', errors recorded, worker alive.
# (A malformed compose file would instead fail `docker compose config`,
# which is the pre-deploy gate story.)
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  "services:`n  worker:`n    environment:`n      EHR_URL: http://invalid:9999`n" | Out-File -Encoding ascii compose.configbad.yaml
  docker compose -f compose.yaml -f compose.configbad.yaml up -d worker
  Start-Sleep 4
  Write-Output "--- worker logs (expect connection errors, process alive) ---"
  docker compose logs --tail 6 worker | Select-String 'connection|error|started'
  Write-Output "--- probe job (expect retries, attempts climbing, NOT lost) ---"
  $raw = curl.exe -s -X POST http://127.0.0.1:8080/api/v1/jobs -H 'Content-Type: application/json' -d '{"type":"appointment","patient_id":1}'
  $id = ([regex]::Match($raw, '"job_id":(\d+)')).Groups[1].Value
  Start-Sleep 10; curl.exe -s "http://127.0.0.1:8080/api/v1/jobs/$id"
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\recover-config.ps1"
} finally { Pop-Location }
