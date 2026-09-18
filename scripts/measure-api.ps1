# Client-side API measurement: requests/sec, p50/p95/p99, error rate.
# Engine-free math lives in scripts/measure.py (unit-tested); this wrapper
# runs it from the repo venv. Run:
# powershell -ExecutionPolicy Bypass -File scripts\measure-api.ps1 -Mode jobs -Requests 200 -Concurrency 10
param([string]$Base = 'http://127.0.0.1:8080',
      [ValidateSet('health', 'jobs')][string]$Mode = 'health',
      [int]$Requests = 200, [int]$Concurrency = 10)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  & '.\.venv\Scripts\python.exe' scripts/measure.py --base $Base --mode $Mode --requests $Requests --concurrency $Concurrency
} finally { Pop-Location }
