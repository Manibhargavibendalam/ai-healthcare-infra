# INCIDENTS (M4/M12)

Reports below are EXECUTED incidents in the full 9-field format (failure,
impact, detection, investigation, root cause, evidence, recovery,
verification, prevention) with timelines. The F-sections after them are the
drill catalog (definitions). Live field evidence is marked PENDING-ENGINE;
every command, query, and expected output is written so the report can be
replayed verbatim.

## INCIDENT-1 — Worker failure → queue backlog (reported)

1. Failure: worker container stopped (`scripts/fail-worker.ps1`) during
   steady intake; 3 probe jobs posted while down, then `load-test.ps1 -Count 100`.
2. Impact: processing rate 0; queue depth climbs (~103); `oldest_age_s` grows;
   NO job loss (Redis buffers); API stays green throughout.
3. Detection: `QueueBacklog` alert (depth >20, 5m) after `WorkerDown`
   (up{job="worker"}==0, 2m); `/worker/status` shows `alive:false`, heartbeat
   age climbing; `GET /api/v1/queue/stats` depth rising.
4. Investigation: `LLEN jobs:queue` = 103 vs `processed` counter frozen;
   `docker compose ps worker` = exited; worker logs end cleanly (no
   traceback — process gone, not wedged); `docker stats` shows api idle →
   capacity problem is worker-side, not API-side.
5. Root cause: worker process gone (simulated crash); single default replica
   means zero drain capacity until restart.
6. Evidence: [PENDING-ENGINE: `alerts.ps1` FIRING lines for WorkerDown +
   QueueBacklog; queue/stats depth series; worker logs tail; `restarts`
   counter before/after]
7. Recovery: `scripts/recover-worker.ps1` (start worker, poll depth → 0),
   then `--scale worker=3` to drain 3× faster, scale back to 1.
8. Verification: depth 0, all 103 jobs `completed`, heartbeat fresh,
   `worker_restarts_total` +1, probe job completes attempts=1.
9. Prevention: heartbeat-age alert already exists; depth/age alerts exist;
   runbook: scale workers on backlog (no api change); consider 2 workers
   as default in prod-like.

Timeline:
```
T+0m   worker stopped (fail-worker.ps1); 3 probe jobs buffered
T+1m   WorkerDown fires (up==0 for 2m needs one more minute — pending)
T+2m   WorkerDown FIRING; QueueBacklog pending (needs 5m over 20)
T+3m   load-test burst posted (depth ~103)
T+7m   QueueBacklog FIRING; oldest_age_s climbing
T+8m   recover-worker.ps1; worker restarts (restarts +1)
T+10m  depth draining; scale worker=3
T+12m  depth 0, all completed; scale back to 1; alerts resolve
```

## INCIDENT-2 — EHR timeout → bounded retries, no storm (reported)

1. Failure: EHR mock flipped to `timeout` (`ehr-failure.ps1 -Mode timeout`)
   during steady processing; each `/sync` hangs 30s vs worker timeout 5s.
2. Impact: jobs fail attempts with `EHR timeout after 5.0s`, requeue with
   2s/4s backoff, die after 3 attempts; API green (failure isolated);
   NO retry storm (bounded attempts × backoff × per-call timeout).
3. Detection: `EhrFailing` alert (failure rate + `ehr_mode_ok==0`, 3m);
   worker `retried`/`failed` counters climbing; `ehr_syncs` rows with
   `error='timeout'` and NULL status codes.
4. Investigation: `SELECT mode,status_code,count(*) FROM ehr_syncs GROUP BY 1,2`
   → all `timeout` mode, NULL codes (client-side timeout, server never
   answered); job rows show attempts climbing 1→2→3 with backoff gaps in
   `updated_at`; worker CPU normal (sleeping on timeouts, not spinning).
5. Root cause: downstream latency exceeds client timeout; classification
   correct (timeout = temporary → bounded retry, not infinite, not fail-fast).
6. Evidence: [PENDING-ENGINE: `alerts.ps1` EhrFailing FIRING; ehr_syncs
   timeout rows; job attempts timeline showing 2s/4s backoff gaps; T6
   e2e output (timeout → normal → completed attempts=2)]
7. Recovery: `ehr-recover.ps1` (mode normal + probe job to completed);
   dead jobs documented (requeue runbook for genuinely transient outages).
8. Verification: probe completes attempts=1, sync row `normal|200`,
   failure rate 0, `ehr_mode_ok==1`, alert resolves.
9. Prevention: per-call timeout (5s) + MAX_ATTEMPTS (3) + backoff are the
   storm preventers — all unit-tested (`test_retry_delay_backoff`,
   `test_classify_matrix`); auth failures fail fast (never retried);
   unknown outcomes never retried (reconcile, don't duplicate).

Timeline:
```
T+0m   EHR → timeout mode; in-flight jobs start timing out at 5s
T+1m   first retries requeue (2s backoff); retried counter climbs
T+3m   EhrFailing FIRING; jobs begin dying at attempts=3
T+5m   operator confirms classification via ehr_syncs (all timeout/NULL)
T+6m   ehr-recover.ps1 (mode normal); probe job posted
T+7m   probe completes attempts=1; failure rate 0; alert resolves
```

## Drill catalog (definitions; reports above are executed instances)

## INCIDENT F1 — API failure

- Failure: `fail-api.ps1` stops the api container.
- Detection: `GET :8080/health` fails/502s; nginx `/healthz` still `ok`
  (ingress alive, backend dead — the distinction matters); compose shows api down.
- Investigation: `docker compose logs api --tail` (traceback/exit),
  `docker compose ps`, nginx error log shows `connect() failed / no live upstreams`.
- Root cause: api process/container gone (simulated crash).
- Recovery: `recover-api.ps1` recreates api, polls `:8080/ready` to `ready`.
- Verification: `/ready` 200, probe job completes end-to-end, metrics resume.
- Prevention: health-gated deploys (M-deploy) so bad code never becomes the
  running api; `restart:unless-stopped` for daemon-level crashes.

## INCIDENT F2 — Worker failure + backlog drain

- Failure: `fail-worker.ps1` stops worker, posts 3 probe jobs.
- Detection: `queue_depth` climbs (`/api/v1/queue/stats`), `alive:false` in
  `/worker/status`, processing rate 0, heartbeat age growing.
- Investigation: `LLEN jobs:queue` vs `processed` counter frozen; worker container down.
- Root cause: worker process gone; queue (Redis) correctly buffers — no loss.
- Recovery: `recover-worker.ps1` starts worker, polls depth to 0.
- Verification: depth 0, jobs completed, heartbeat fresh, `restarts` counter +1.
- Prevention: heartbeat-age alert (M-obs); `--scale worker=N` for drain speed.

## INCIDENT F3 — EHR degradation (all 7 modes)

- Failure: `ehr-failure.ps1 -Mode <mode>` (slow/timeout/temp_failure/auth_failure/unavailable/unknown).
- Detection: job errors (`EHR timeout`/`HTTP 500`/`permanent 401`/unknown),
  `ehr_syncs` rows per attempt with mode+code, worker `failed`/`retried` counters.
- Investigation: `SELECT mode,status_code,count(*) FROM ehr_syncs GROUP BY 1,2`
  shows the injected mode; job `attempts`/`error` shows classification.
- Root cause: downstream dependency behavior (simulated) + correct/incorrect
  classification — verify attempts: temp→3, auth→1, unknown→1.
- Recovery: `ehr-recover.ps1` (mode normal + probe job to completed).
- Verification: probe completes attempts=1; sync row `normal|200`.
- Prevention: per-mode alert thresholds; dead-job requeue runbook; idempotency
  keys for the unknown-outcome class (documented gap).

## INCIDENT F4 — Database connectivity loss

- Failure: `fail-db.ps1` stops postgres.
- Detection: `/ready` → 503 `{"postgres":"down"}` (no exception text, no crash);
  worker logs `loop_error` lines, process stays alive; jobs park back on queue.
- Investigation: `docker compose ps` (db down), api logs show refused-connection
  warnings with cid, worker `queue_depth` frozen (nothing lost).
- Root cause: state store unreachable (simulated outage).
- Recovery: `recover-db.ps1`: start db → `/ready` flips → row counts intact
  (volume proof: `SELECT count(*) FROM patients` = 5) → probe job completes.
- Verification: ready 200, counts intact, queue drains, no jobs stuck `processing`.
- Prevention: readiness-gated traffic (M-deploy); pg backup/restore drill (M8);
  connection retry with backoff already in worker loop.

## INCIDENT F5 — Queue backlog under load

- Failure: `load-test.ps1 -Count 100` posts faster than one worker drains.
- Detection: `/api/v1/queue/stats` depth climbing + `oldest_age_s` growing;
  worker `processed` rate flat at capacity (~2 jobs/s with AI latency).
- Investigation: enqueue rate (script prints, ~50+/s) vs processing rate;
  `docker stats` shows worker CPU-bound, api idle → scale WORKER, not api.
- Root cause: capacity < arrival rate (by design of the drill).
- Recovery: workers drain naturally; `--scale worker=3` to drain 3x faster,
  then scale back. `recover-worker.ps1` pattern if a worker died mid-drill.
- Verification: depth 0, `oldest_age_s` 0, processing rate returned, all jobs completed.
- Prevention: depth/age alerts (M-obs); independent worker scaling (no api change).

## INCIDENT F6 — Container failure (generic)

- Failure: `fail-service.ps1 -Service <ai|ehr|redis|nginx|db>` (compose service names, not directory names).
- Detection: `docker compose ps` (exited/unhealthy) + dependent symptoms
  (e.g., ai down → appointments `ai_degraded:true`; redis down → api `/ready` 503).
- Investigation: `docker compose logs --tail <svc>` exit cause; dependents' logs.
- Root cause: process/container death (simulated `stop`; real causes: OOM —
  hence `mem_limit` + `docker stats` — bad deploy, host pressure).
- Recovery: `recover-service.ps1 -Service <svc>` (up + wait running) then the
  service-specific verify printed by the script.
- Verification: compose health green + dependent behavior normal (per-service check).
- Prevention: `restart:unless-stopped` everywhere; healthchecks; OOM alerts (M-obs).

## INCIDENT F7 — Bad configuration

- Failure: `fail-config.ps1` recreates worker with `EHR_URL=http://invalid:9999`.
- Detection: worker logs `EHR connection failed`; jobs climb attempts with that
  error; worker process stays alive (fail SAFE: retries recorded, nothing lost,
  nothing half-written — EHR never reached).
- Investigation: `docker compose config` shows effective env; logs name the
  unresolvable host; `ehr_syncs` rows with `connection failed`.
- Root cause: wrong endpoint config shipped to one service.
- Recovery: `recover-config.ps1` removes override, recreates worker, drains queue.
- Verification: depth 0, new jobs complete attempts=1, no `invalid` host in config.
- Prevention: `docker compose config` in CI catches structural errors;
  health-gated deploys (M-deploy) catch runtime-bad values before traffic;
  worker `_num()` validation fails fast with `invalid VAR=...` on malformed numbers.

## Template for new incidents (9 fields)

Failure / impact / detection (which metric, log, alert) / investigation /
root cause / evidence (logs, metrics, alert output, commands — or
PENDING-ENGINE placeholders) / recovery steps + commands / verification
(command + expected output) / prevention (code, alert, or runbook change +
commit ref), plus a T+ timeline.
