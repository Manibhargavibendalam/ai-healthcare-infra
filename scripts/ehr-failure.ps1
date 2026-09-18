# FAILURE 3 (inject): set EHR failure mode. Repeatable, no restarts.
# Modes: normal | slow | timeout | temp_failure | auth_failure | unavailable | unknown
param([Parameter(Mandatory=$true)][ValidateSet('normal','slow','timeout','temp_failure','auth_failure','unavailable','unknown')][string]$Mode)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose exec -T ehr-mock python /scripts/svc.py 8002 POST /mode "{`"mode`":`"$Mode`"}"
  Write-Output "EHR mode=$Mode. Expected job behavior:"
  Write-Output "  slow         -> completes, processing_ms >= ~3000"
  Write-Output "  timeout      -> retries w/ backoff (2s,4s), then failed"
  Write-Output "  temp_failure -> retries x3 (HTTP 500), then failed"
  Write-Output "  auth_failure -> failed immediately, attempts=1 (never retried)"
  Write-Output "  unavailable  -> retries x3 (HTTP 503), then failed"
  Write-Output "  unknown      -> failed, attempts=1, reconcile (never retried)"
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\ehr-recover.ps1"
} finally { Pop-Location }
