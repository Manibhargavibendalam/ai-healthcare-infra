# Generic recovery: recreates/starts a service and waits until it is running.
# Run: powershell -ExecutionPolicy Bypass -File scripts\recover-service.ps1 -Service ai
param([Parameter(Mandatory=$true)][string]$Service, [int]$TimeoutSec = 120)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose up -d $Service
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $st = docker compose ps $Service --format '{{.Status}}' 2>$null | Out-String
    if ($st -match 'running|healthy|Up') { Write-Output "RECOVERED ${Service}: $($st.Trim())"; break }
    Start-Sleep 5
  }
  docker compose ps --format '{{.Name}} {{.Status}}' | Select-String $Service
  Write-Output "Verify per service: api->curl :8080/ready | worker->queue drains | db->row counts intact"
} finally { Pop-Location }
