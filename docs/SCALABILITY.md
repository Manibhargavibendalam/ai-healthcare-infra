# SCALABILITY

API and workers scale independently (separate knobs, separate bottlenecks).

## Mechanics

- API: `scripts/scale-api.ps1 -Count N` (`--scale api=N`); nginx re-resolves
  via embedded DNS (5s TTL) — a static upstream would pin one replica (D26).
- Workers: `scripts/scale-worker.ps1 -Count N`; the shared Redis queue IS the
  balancer — no coordination code needed.

## Measurement (no unmeasured claims)

`measure-api.ps1` (rps, p50/p95/p99, errors), `measure-workers.ps1`
(jobs/sec, depth, age), `db/stats` (query ms, connections), `queue/stats`
(depth, oldest age = queue latency), `measure-startup.ps1` (per-service
readiness timing), Locust shapes (normal/api-heavy/job-poster/burst).
Numbers table lives in `../SCALING.md` (PENDING-ENGINE by design).

## Bottlenecks (predicted, to confirm by measuring)

1. Worker ≈ 1/(EHR+AI latency) ≈ 2 jobs/s each — AI 0.5s sleep dominates.
2. API DB access has no pool (connect per request) — fine at sim rates.
3. Single host CPU/RAM bounds everything (`docker stats` arbitrates).
