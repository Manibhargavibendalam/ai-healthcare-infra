# FAILURE 5: burst more jobs than worker capacity, then measure the drain.
# Reports enqueue rate, max depth, drain time, processing rate, oldest age.
param([string]$A = 'http://127.0.0.1:8080', [int]$Count = 100, [int]$TimeoutSec = 300)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $before = ((curl.exe -s $A/worker/status | Select-String -Pattern '"processed":(\d+)' ).Matches[0].Groups[1].Value)
  $sw = [Diagnostics.Stopwatch]::StartNew()
  1..$Count | ForEach-Object { curl.exe -s -X POST $A/api/v1/jobs -H 'Content-Type: application/json' -d '{"type":"load","patient_id":1}' | Out-Null }
  $sw.Stop()
  $enqRate = [math]::Round($Count / [math]::Max($sw.Elapsed.TotalSeconds, 0.01), 1)
  Write-Output "enqueued $Count in $($sw.Elapsed.TotalSeconds.ToString('0.0'))s ($enqRate jobs/s)"
  $maxDepth = 0; $t0 = Get-Date
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $qs = curl.exe -s "$A/api/v1/queue/stats" | ConvertFrom-Json
    if ($qs.queue_depth -gt $maxDepth) { $maxDepth = $qs.queue_depth }
    if ($qs.queue_depth -eq 0) { break }
    Start-Sleep 3
  }
  $drainSecs = ((Get-Date) - $t0).TotalSeconds
  $after = ((curl.exe -s $A/worker/status | Select-String -Pattern '"processed":(\d+)').Matches[0].Groups[1].Value)
  $procRate = [math]::Round(([int]$after - [int]$before) / [math]::Max($drainSecs, 0.01), 2)
  Write-Output "BACKLOG RESULT: max_depth=$maxDepth drain_s=$([math]::Round($drainSecs,1)) processing_rate=$procRate jobs/s"
  Write-Output "queue stats now: $(curl.exe -s $A/api/v1/queue/stats)"
} finally { Pop-Location }
