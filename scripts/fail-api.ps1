# FAILURE 1 (inject): API dies; ingress stays alive (502), backend unreachable.
param([string]$A = 'http://127.0.0.1:8080')
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose stop api
  Write-Output "--- via ingress /health (expect FAILURE/502) ---"
  curl.exe -s --max-time 5 $A/health; Write-Output "curl exit=$LASTEXITCODE"
  Write-Output "--- ingress self-check /healthz (expect ok: nginx alive, backend dead) ---"
  curl.exe -s --max-time 5 $A/healthz; Write-Output ""
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\recover-api.ps1"
} finally { Pop-Location }
