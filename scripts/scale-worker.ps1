# Independent worker scaling: N replicas share the same queue.
# Proves processing capacity scales without touching the API.
param([int]$Count = 3)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose up -d --scale worker=$Count
  Start-Sleep 8
  $n = (docker compose ps worker --format '{{.Name}}' | Measure-Object -Line).Lines
  Write-Output "worker replicas running: $n (asked $Count)"
  Write-Output "worker status: $(curl.exe -s http://127.0.0.1:8080/worker/status)"
  Write-Output "Scale back when done: docker compose up -d --scale worker=1"
  Write-Output 'Then measure drain: load-test.ps1 -Count 100, then measure-workers.ps1 -WindowSec 30'
} finally { Pop-Location }
