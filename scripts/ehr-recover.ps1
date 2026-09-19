# FAILURE 3 (recover): EHR back to normal; probe job must complete.
param([string]$A = 'http://127.0.0.1:8080', [int]$TimeoutSec = 120)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose exec -T ehr python /scripts/svc.py 8002 POST /mode '{"mode":"normal"}'
  $raw = curl.exe -s -X POST $A/api/v1/jobs -H 'Content-Type: application/json' -d '{"type":"appointment","patient_id":1}'
  $id = ([regex]::Match($raw, '"job_id":(\d+)')).Groups[1].Value
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $s = curl.exe -s "$A/api/v1/jobs/$id"
    if ($s -match '"status":"completed"') { Write-Output "RECOVERED: $s"; break }
    Start-Sleep 3
  }
} finally { Pop-Location }
