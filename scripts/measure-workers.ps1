# Worker capacity measurement: sample stats twice over a window, report rates.
# Metrics: jobs/sec, depth delta, oldest age, failed/retried deltas, worker count.
param([string]$A = 'http://127.0.0.1:8080', [int]$WindowSec = 30)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  function snap {
    $w = curl.exe -s "$A/worker/status" | ConvertFrom-Json
    $q = curl.exe -s "$A/api/v1/queue/stats" | ConvertFrom-Json
    return @{ proc = $w.processed; fail = $w.failed; ret = $w.retried; depth = $q.queue_depth; age = $q.oldest_age_s }
  }
  $s1 = snap; Start-Sleep $WindowSec; $s2 = snap
  $n = $s2.proc - $s1.proc
  $rate = [math]::Round($n / [math]::Max($WindowSec, 1), 2)
  $workers = (docker compose ps worker --format '{{.Name}}' | Measure-Object -Line).Lines
  Write-Output "WORKERS: count=$workers processed+=$n in ${WindowSec}s => $rate jobs/sec"
  Write-Output "depth $($s1.depth)->$($s2.depth) oldest_age_s=$($s2.age) failed+=$($s2.fail - $s1.fail) retried+=$($s2.ret - $s1.ret)"
} finally { Pop-Location }
