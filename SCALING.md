# SCALING & PERFORMANCE (M5)

Independent scaling is mechanical; measurement is honest. No number below
is claimed without running the command next to it. Sections marked
PENDING-ENGINE get filled the moment the engine runs (commands staged).

## What scales independently (and how)

API (stateless replicas, nginx balances via DNS re-resolution):
```powershell
scripts\scale-api.ps1 -Count 3        # up -d --scale api=3, verify via ingress
docker compose up -d --scale api=1    # back to one
```
Worker (shared queue, no coordination needed):
```powershell
scripts\scale-worker.ps1 -Count 3
docker compose up -d --scale worker=1
```
Why nginx needed a resolver (D26): a static upstream resolves once and pins
to one replica; `resolver 127.0.0.11 valid=5s` + `set $backend api`
re-resolves per TTL across all replica IPs.

## How each metric is measured (no new server code except db/stats)

| Metric | Source | Command |
|---|---|---|
| API rps, p50/p95/p99, error rate | client-side threaded measurer | `measure-api.ps1 -Mode jobs -Requests 200 -Concurrency 10` |
| API CPU/memory | container stats | `docker stats --no-stream` during load |
| Worker jobs/sec, depth, oldest age, failed/retried | `/worker/status` + `/api/v1/queue/stats` deltas | `measure-workers.ps1 -WindowSec 30` |
| DB query ms, connections, max | `GET /api/v1/db/stats` | curl during load |
| Queue latency | `oldest_age_s` in queue stats | sampled by load-test/measure scripts |
| Startup/readiness per service | recreate + poll loop | `measure-startup.ps1` (asks first: destroys volumes) |
| Burst behavior | locust, zero-wait class | `docker compose --profile loadgen run --rm locust --headless -u 100 -r 20 --run-time 60s --host http://nginx:8080` |
| Workload shapes | locust classes | NormalUser / ApiHeavy / JobPoster / BurstUser (weights 4/2/2/1) |

## Bottleneck hypotheses (to CONFIRM by measuring, in order)

1. **Worker throughput ≈ 1 / (EHR + AI latency)** ≈ 2 jobs/s per worker at
   defaults — the AI 0.5s sleep dominates. Predicted first ceiling.
2. **API DB access has no pool** (one `psycopg2.connect` per request): fine at
   simulation rates, connection churn + `max_connections` is the ceiling under
   high concurrency. Fix path: PgBouncer/persistent pool (documented, not built).
3. **Single host**: CPU/RAM of the laptop bounds everything; `docker stats`
   shows who saturates first.
4. nginx + Redis + Postgres overhead: expected negligible locally; verify via
   `db/stats` query_ms vs API p50 gap.

## Simulation limits (stated openly)

Single Docker host · no TLS on loopback · compose DNS (5s TTL, not real LB
health-aware routing) · Prometheus per-replica sampling under `--scale api`
(single DNS target round-robins scrapes) · locust-in-container shares host CPU
with the system under test (measure-api from host venv is cleaner for latency).

## What would scale in a real cloud (translation)

| Local | Cloud | Scales by |
|---|---|---|
| `--scale api=N` + nginx | ALB target group + ECS `api_count` | request rate; HPA on latency/CPU |
| `--scale worker=N` + Redis list | ECS `worker_count` + SQS/ElastiCache | queue depth/age; HPA on backlog |
| postgres container + pg_dump | RDS (Multi-AZ, read replicas) | connections (pooler), storage, replicas |
| redis container | ElastiCache (cluster/failover) | memory, connections |
| locust container | distributed locust / k6 cloud | load-generator fleet |

## Measured numbers (PENDING-ENGINE — fill with the commands above)

| Scenario | API p50/p95 | err% | worker jobs/s | max depth | drain s | bottleneck |
|---|---|---|---|---|---|---|
| baseline (1+1) | — | — | — | — | — | — |
| api×3, jobs 200/10 | — | — | — | — | — | — |
| worker×3, burst 100 | — | — | — | — | — | — |
| backlog 100, 1 worker | — | — | — | — | — | — |

## Trade-offs

Accuracy vs cost: client-side measurement is free and honest but includes
loopback+harness noise; server histograms (already exported) are cleaner for
dashboards (M-obs). Replicas vs resources: scaling replicas on one host
splits the same CPU — throughput gains flatten (Amdahl); the exercise proves
MECHANICS (balancing, shared queue, independent knobs), not cloud numbers.
