# Independent API scaling: N replicas behind nginx (resolver re-resolves DNS).
# Proves horizontal API capacity without touching workers.
param([int]$Count = 3)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose up -d --scale api=$Count
  Start-Sleep 12  # replicas healthy + nginx 5s DNS TTL refresh
  $n = (docker compose ps api --format '{{.Name}}' | Measure-Object -Line).Lines
  Write-Output "api replicas running: $n (asked $Count)"
  1..($n * 2) | ForEach-Object { curl.exe -s --max-time 5 http://127.0.0.1:8080/health | Out-Null }
  if ($LASTEXITCODE -eq 0) { Write-Output 'ingress serving across replicas (no errors)' }
  Write-Output "Scale back when done: docker compose up -d --scale api=1"
  Write-Output 'Then measure: measure-api.ps1 -Mode health -Requests 500 -Concurrency 25'
} finally { Pop-Location }
