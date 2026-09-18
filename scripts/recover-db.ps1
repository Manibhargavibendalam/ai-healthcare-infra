# FAILURE 4 (recover): DB returns; readiness flips; data intact (volume proof).
param([string]$A = 'http://127.0.0.1:8080', [int]$TimeoutSec = 120)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $pp = ((Get-Content .\.env | Select-String '^POSTGRES_PASSWORD=').Line.Split('=')[1])
  docker compose start db
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $r = curl.exe -s --max-time 5 $A/ready
    if ($r -match '"status":"ready"') { Write-Output "RECOVERED: $r"; break }
    Start-Sleep 5
  }
  Write-Output "--- data survived restart (volume proof) ---"
  docker compose exec -T -e "PGPASSWORD=$pp" db psql -U app -d healthcare -t -A -c "SELECT count(*) FROM patients;"
  $raw = curl.exe -s -X POST $A/api/v1/jobs -H 'Content-Type: application/json' -d '{"type":"appointment","patient_id":1}'
  $id = ([regex]::Match($raw, '"job_id":(\d+)')).Groups[1].Value
  Start-Sleep 8; curl.exe -s "$A/api/v1/jobs/$id"
} finally { Pop-Location }
