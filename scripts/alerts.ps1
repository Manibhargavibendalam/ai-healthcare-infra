# Alert viewer: firing/pending from Prometheus + recent webhook receipts.
# The single command to run DURING a drill to prove an alert fired.
# Run: powershell -ExecutionPolicy Bypass -File scripts\alerts.ps1
param([string]$Prom = 'http://127.0.0.1:9090')
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  Write-Output '--- Prometheus active (firing + pending) ---'
  try {
    $r = Invoke-RestMethod "$Prom/api/v1/alerts" -TimeoutSec 10
    $firing = @($r.data.alerts | Where-Object { $_.state -eq 'firing' })
    $pending = @($r.data.alerts | Where-Object { $_.state -eq 'pending' })
    Write-Output "firing=$($firing.Count) pending=$($pending.Count)"
    $firing | ForEach-Object { Write-Output "  FIRING $($_.labels.alertname) [$($_.labels.severity)] since $($_.activeAt)" }
    $pending | ForEach-Object { Write-Output "  pending $($_.labels.alertname) [$($_.labels.severity)]" }
  } catch { Write-Output "prometheus unreachable: $($_.Exception.Message)" }
  Write-Output '--- alert-api recent receipts ---'
  try {
    $a = docker compose exec -T alert-api python -c "import urllib.request,json;print(urllib.request.urlopen('http://localhost:8080/alerts?n=5',timeout=5).read().decode())" 2>$null
    if ($a) { $j = $a | ConvertFrom-Json; Write-Output "stored_recent=$($j.count)"; $j.alerts | ForEach-Object { Write-Output "  $($_.status) alerts=$(@($_.alerts).Count) at $($_.ts)" } }
    else { Write-Output 'alert-api unreachable (stack down?)' }
  } catch { Write-Output "alert-api unreachable: $($_.Exception.Message)" }
} finally { Pop-Location }
