# FAILURE 2 (recover): worker restarts, queue drains, heartbeat fresh.
param([string]$A = 'http://127.0.0.1:8080', [int]$TimeoutSec = 180)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $rp = ((Get-Content .\.env | Select-String '^REDIS_PASSWORD=').Line.Split('=')[1])
  docker compose start worker
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $depth = (docker compose exec -T redis redis-cli -a $rp LLEN jobs:queue | Out-String).Trim()
    if ($depth -eq '0') { break }
    Start-Sleep 3
  }
  Write-Output "queue depth: $depth (expect 0)"
  Write-Output "worker status: $(curl.exe -s $A/worker/status)"
  docker compose logs --tail 5 worker
} finally { Pop-Location }
