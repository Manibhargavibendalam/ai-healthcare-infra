# FAILURE 1 (recover): API returns, readiness gates traffic again.
param([string]$A = 'http://127.0.0.1:8080', [int]$TimeoutSec = 120)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose up -d api
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $r = curl.exe -s --max-time 5 $A/ready
    if ($r -match '"status":"ready"') { Write-Output "RECOVERED: $r"; break }
    Start-Sleep 5
  }
  curl.exe -s "$A/api/v1/jobs/1"
} finally { Pop-Location }
