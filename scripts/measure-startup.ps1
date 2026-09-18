# Startup/readiness timing: full recreate, per-service healthy timestamps.
# Reports deployment duration (down->all-healthy), startup and readiness per
# service. DESTRUCTIVE (down -v destroys volumes): confirm first.
param([int]$TimeoutSec = 300)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $c = Read-Host 'Destroy ALL volumes and re-time startup? (yes/no)'
  if ($c -ne 'yes') { Write-Output 'aborted'; return }
  docker compose down -v | Out-Null
  $t0 = Get-Date
  docker compose up -d | Out-Null
  $ready = @{}
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while (((Get-Date) -lt $deadline) -and ($ready.Count -lt 7)) {
    docker compose ps --format '{{.Name}} {{.Health}} {{.Status}}' | ForEach-Object {
      if (($_ -match 'healthy|running') -and ($_ -match '(db|redis|api|ai|ehr|worker|nginx)')) {
        $svc = $Matches[1]
        if (-not $ready.ContainsKey($svc)) { $ready[$svc] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
      }
    }
    Start-Sleep 5
  }
  Write-Output 'STARTUP (seconds from up -d to healthy/running):'
  $ready.GetEnumerator() | Sort-Object Value | ForEach-Object { Write-Output "  $($_.Key): $($_.Value)s" }
  $total = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
  Write-Output "deployment duration (down->monitoring this script): ${total}s for $($ready.Count)/7 services"
} finally { Pop-Location }
