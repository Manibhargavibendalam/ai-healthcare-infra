# RESILIENCE ANALYSIS (SPOF)

For each: dependency → failure mode → impact → detection → recovery →
SPOF? → mitigation → trade-off. No SPOF is pretended away; acceptable risks
for a local simulation are named.

| System | Depends on | Fails as | Impact | Detected by | Recovery | SPOF? | Mitigation | Trade-off |
|---|---|---|---|---|---|---|---|---|
| API (1 replica) | db, redis, ai | 502s at ingress | total intake outage | ApiDown alert | recreate; scale to N | YES (default) | `--scale api`, resolver LB | replicas cost RAM; default 1 keeps laptop light |
| Worker (1 replica) | redis, db, ehr, ai | rate 0, queue grows | backlog, latency; no loss | WorkerDown + QueueBacklog | restart; scale to drain | YES (default) | shared queue, backoff | same as API |
| Queue (Redis) | — (hosts state) | refuse/enqueue fail | intake + processing halt | /ready redis down | recreate; AOF replay | YES | AOF, password, private net | cluster/failover needs real infra |
| Database | volume | 503s, jobs park | writes/reads halt; volume keeps data | PostgresDown, DB_ERR | restart (volume) / restore (loss) | YES | backups + counts verify; RDS snapshots in AWS | Multi-AZ + PITR cost real money |
| EHR (mock) | — (external) | timeout/5xx/401 | jobs retry→fail; API green | EhrFailing, ehr_syncs | mode normal / restart | NO (isolated by design) | classification: temp/permanent/unknown | real EHR needs idempotency keys (gap) |
| Deploy (script) | registry, daemon | exit≠0 | no new releases; running version safe | CI red, exit codes | fix forward / rollback.sh | NO (nothing to roll back when blocked) | gates, history, refusal | operator-run, no server |
| Monitoring | scrape targets | blind ops | missed alerts; serving continues | up==0, gaps | recreate overlay | PARTIAL (fate-sharing host) | separate overlay + volumes | separate host = real cost |

Source detail: `../RECOVERY.md` (procedures), `../INCIDENTS.md` (lifecycles).
