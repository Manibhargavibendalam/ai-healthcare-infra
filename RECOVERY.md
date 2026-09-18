# RECOVERY

Recreating infrastructure and recovering persistent state are SEPARATE
concerns. The first is code (`compose.yaml`, `init.sql`); the second is data
(`pg_dump`).

## Recovery objectives (DESIGN TARGETS for the simulation)

These are targets the design aims at — measured values get filled on the
first live run (`measure-startup.ps1` times recreation; restore timing is
measured during the backup drill). A target is not a guarantee.

| Objective | Target | Meaning |
|---|---|---|
| RTO infra (recreate) | < 5 min | `down -v` → `up -d` → all healthchecks green (code-only, no data) |
| RTO state (restore) | < 10 min | dump applied + counts match + probe job completes |
| RPO (max data loss) | last `backup.sh` run | manual cadence locally (run before risky ops); RDS 7-day automated backups in AWS |
| RPO queue (accepted loss) | unbounded | Redis is ephemeral BY DESIGN: destroyed volumes lose queued-but-unprocessed jobs; completed work lives in Postgres and is restorable |

Rows stuck in `processing` after a crash are visible and requeueable, never silent.

## Procedures (the full loop: state → backup → loss → recreate → restore → verify)

```bash
# 1. state: note counts + post a canary job, 2. backup (verifies itself):
bash scripts/backup.sh        # writes backups/manual-<ts>.sql + .counts (pre-counts + COPY markers + size asserted)
# 3. loss:  docker compose down -v
# 4. recreate (INFRA ONLY — jobs history starts empty, migrations re-seed registry):
docker compose up -d
# 5. restore (STATE): answers yes, applies with ON_ERROR_STOP=1, compares counts:
bash scripts/restore.sh backups/manual-<ts>.sql
# 6. verify: probe job via :8080 completes end-to-end (see DEMO_RUNBOOK.md recovery)
```

Component-level (no data loss): `docker compose stop db && docker compose start db`
→ volume intact → `/ready` flips → counts unchanged (fast path, no restore needed).

## Single point of failure analysis

| System | If unavailable | Impact | Detection | Recovery | Mitigation | Remaining limitation |
|---|---|---|---|---|---|---|
| API (1 replica default) | ingress 502s | total outage, jobs still enqueue? NO — intake dead | ApiDown alert, /healthz ok vs /health fail | recreate container; `scale-api.ps1` for N | `--scale api`, resolver LB | single replica by default; cold start |
| Worker | queue grows, rate 0 | backlog, latency grows; nothing lost | WorkerDown + QueueBacklog alerts, heartbeat age | restart; scale workers to drain | shared queue, backoff, `--scale worker` | 1 worker default; backlog needs operator scale |
| Queue (Redis) | api can't enqueue, worker starves | intake + processing halt | /ready 503 (redis down), LLEN fails | recreate; AOF replays | AOF persistence, password, private net | single instance; in-flight loss on volume destroy |
| Database | /ready 503, worker parks jobs | writes halt; reads halt; no loss (volume) | PostgresDown alert, DB_ERR counter | restart (volume) or restore (loss) | backups + `.counts` verify, RDS snapshots in AWS | single instance; manual restore step |
| EHR (external) | timeouts/5xx/401s | jobs retry→fail; API stays green (isolated) | EhrFailing alert, ehr_syncs rows, failed counter | mode normal / restart mock | classification (temp retry, perm fail-fast, unknown no-retry) | real EHR would need idempotency keys (gap) |
| Deploy system | no new releases | changes queue in git; running version unaffected | CI red / deploy.sh exit≠0 | fix forward or rollback.sh | verify-before-replace, history, refuse-empty | deploy.sh runs on operator host (no server) |
| Monitoring | blind ops | alerts stop; system keeps serving | Prometheus `up==0`, missing scrapes | recreate overlay; 30d? no — promdata volume | separate overlay, own volumes | monitoring shares the same host (fate-sharing) |

## What lives where

| State | Location | Recovery |
|---|---|---|
| Registry + jobs + sync audit | `pgdata` volume | pg_dump/restore; RDS snapshots in AWS |
| Queue (in-flight) | `redisdata` volume (AOF) | best-effort; loss accepted, jobs re-submittable |
| Secrets | `.env` (gitignored, NOT backed up in repo) | regenerate via bootstrap; CI secrets in AWS |
| Everything else | code | `git clone` + `compose up` |

## Failure drills mapped to recovery

DB container stop → readiness 503, restart, data intact (volume).
DB volume destroy → reseed + restore from dump (RPO demo).
Full `down -v` → full recreation timing (RTO demo). All in `DEMO_RUNBOOK.md` §9.
