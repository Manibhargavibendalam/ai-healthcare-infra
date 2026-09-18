# FAILURE 2 (inject): worker stops; jobs must BUFFER in Redis, not vanish.
# Expects: LLEN grows, processing rate 0, worker/status alive=false.
param([string]$A = 'http://127.0.0.1:8080')
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose stop worker
  1..3 | ForEach-Object { curl.exe -s -X POST $A/api/v1/jobs -H 'Content-Type: application/json' -d '{"type":"appointment","patient_id":1}' | Out-Null }
  $rp = ((Get-Content .\.env | Select-String '^REDIS_PASSWORD=').Line.Split('=')[1])
  $depth = docker compose exec -T redis redis-cli -a $rp LLEN jobs:queue
  Write-Output "worker STOPPED. queue depth now: $($depth.Trim()) (must be >= 3)"
  Write-Output "worker status: $(curl.exe -s $A/worker/status)"
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\recover-worker.ps1"
} finally { Pop-Location }
