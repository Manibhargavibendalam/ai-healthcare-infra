# Generic failure injector: stops any service. Specific scenarios have
# dedicated scripts (fail-worker/api/db); use this for the rest (ai, ehr, redis, nginx).
# Run: powershell -ExecutionPolicy Bypass -File scripts\fail-service.ps1 -Service ai
param([Parameter(Mandatory=$true)][string]$Service)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose stop $Service
  docker compose ps --format '{{.Name}} {{.Status}}' | Select-String $Service
  Write-Output "STOPPED $Service."
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\recover-service.ps1 -Service $Service"
} finally { Pop-Location }
