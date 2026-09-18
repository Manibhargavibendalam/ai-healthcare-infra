# INCIDENT REPORT — INCIDENT-1: worker failure → queue backlog

The deepest-documented incident (PDF §19: at least one in detail).
INCIDENT-2 (EHR timeout) is fully reported in `INCIDENTS.md`; drill
definitions F1–F7 live there too.

## 1. Failure

Worker container stopped (`scripts/fail-worker.ps1`) during steady intake;
3 probe jobs buffered, then `load-test.ps1 -Count 100` burst (~103 queued).

## 2. Impact

Processing rate 0; depth ~103; `oldest_age_s` climbing. Zero job loss
(Redis buffers). API stays green — intake and processing fail independently.

## 3. Detection

`WorkerDown` (up{job="worker"}==0, 2m) then `QueueBacklog` (depth>20, 5m);
`/worker/status` → `alive:false`, heartbeat aging; `queue/stats` rising.
Command: `scripts/alerts.ps1`.

## 4. Investigation

`LLEN jobs:queue`=103 vs `processed` frozen; `docker compose ps worker` =
exited; logs end cleanly (gone, not wedged); `docker stats` shows api idle →
worker-side capacity problem. Correlation ids join api→queue→worker→DB rows.

## 5. Root cause

Worker process gone (simulated crash); single default replica = zero drain
capacity until restart. Queue design (BRPOPLPUSH) held: nothing lost.

## 6. Evidence

[PENDING-ENGINE: alerts.ps1 FIRING lines; queue/stats series; worker log
tail; `worker_restarts_total` before/after; Grafana queue tile.]

## 7. Recovery

`scripts/recover-worker.ps1` (start, poll depth→0) → `--scale worker=3`
(3× drain) → scale back to 1.

## 8. Verification

Depth 0, all 103 `completed`, heartbeat fresh, restarts +1, probe job
attempts=1, alerts resolve.

## 9. Prevention

Heartbeat/depth/age alerts exist; runbook scales workers (never api) on
backlog; prod-like default of 2 workers recommended.

Timeline: T+0 stop+buffer → T+2 WorkerDown → T+3 burst → T+7 QueueBacklog →
T+8 restart → T+10 scale-3 → T+12 drained, resolved.
