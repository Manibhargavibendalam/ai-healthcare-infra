# FAILURE 4 (inject): DB connectivity lost. API must 503 (not crash),
# worker must stay alive and park jobs (loop_error + requeue, no crash-loop).
param([string]$A = 'http://127.0.0.1:8080')
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  docker compose stop db
  Start-Sleep 3
  Write-Output "--- /ready (expect 503 naming postgres, NO exception text) ---"
  curl.exe -s --max-time 5 $A/ready; Write-Output ""
  Write-Output "--- worker logs (expect loop_error, process alive) ---"
  docker compose logs --tail 6 worker | Select-String 'loop_error|started|error'
  docker compose ps --format '{{.Name}} {{.Status}}' | Select-String 'worker|api'
  Write-Output "Recover: powershell -ExecutionPolicy Bypass -File scripts\recover-db.ps1"
} finally { Pop-Location }
