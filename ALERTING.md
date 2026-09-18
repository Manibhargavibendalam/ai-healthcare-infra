# ALERTING (M7)

Pipeline: Prometheus evaluates `alert.rules.yml` every 15s → firing alerts
go to Alertmanager (`alertmanager:9093`) → grouped by alertname → webhook
`POST alert-api:8080/alerts` → JSONL log + `GET /alerts` + counters.
Read alerts: Prometheus UI `/-/alerts` (:9090), `scripts/alerts.ps1`, or
`docker compose exec alert-api` + `GET /alerts`.

## Noise policy (why pages stay rare)

One tier per condition (no warn+crit duplicates) · `for:` 1m hard-down,
3–5m rates, 10m saturation · group_wait 30s + group_interval 2m merge flaps ·
repeat 4h (1h critical) · thresholds mirror Grafana so screens and pages agree.

## The 10 alerts (name · condition · threshold · severity · likely cause → action → verify)

| # | Name | Condition (expr) | Threshold / for | Sev | Likely cause → Operator action → Verify |
|---|---|---|---|---|---|
| 1 | ApiDown | `up{job="api"}==0` | 1m | critical | api stopped/OOM → `ps`+logs, `recover-api.ps1` → `:8080/ready` ready, `up==1` |
| 2 | ApiHighErrorRate | 5xx share | >5% / 5m | warning | bad deploy, DB/Redis down → ready+logs by cid, rollback if post-deploy → err% <1%, probe jobs ok |
| 3 | ApiHighLatency | p95 `api_http_request_duration_seconds` | >1s / 5m | warning | slow DB/AI, host saturation → `db/stats`, AI latency, `docker stats` → p95 <0.5s 10m |
| 4 | WorkerDown | `up{job="worker"}==0` | 2m | critical | worker stopped/crashed → `ps`+`loop_error` logs, `recover-worker.ps1` → alive:true, depth→0 |
| 5 | QueueBacklog | `queue_depth` | >20 / 5m | warning | worker slow, EHR retries, burst → worker/status, EHR mode, scale-worker → depth falling, age <30s |
| 6 | PostgresDown | `pg_up==0` | 1m | critical | db stopped/creds → `ps`+logs, `recover-db.ps1` → `pg_up==1`, counts intact |
| 7 | DeployFailed | `increase(deploy_failed_total[10m])>0` | 1m | critical | candidate /ready failing → read deploy log, fix, re-deploy → build pinned, probe ok |
| 8 | NodeSaturation | CPU>80% or mem>85% | 10m | warning | burst sharing host, too many replicas → `docker stats`, scale back → CPU<60%, mem<70% 15m |
| 9 | SecurityGateFailing | `min(security_gate_ok)==0` | 1m | critical | secret/vuln/misconfig → run `ci.sh` security stage, fix → all gates 1 |
| 10 | EhrFailing | failure rate or `ehr_mode_ok==0` | 3m | warning | mode drill/outage, 401s → ehr /mode, `ehr_syncs`, recover → rate 0, probe attempts=1 |

Gate/deploy signals originate OUTSIDE Prometheus: `ci.sh` posts
`/gates{name,ok}`, `deploy.sh` posts `/deploys{version,status}`; alert-api
holds the gauges/counters Prometheus scrapes. Gauges are in-memory (restart
resets); CI reposts every run, so steady state stays fresh.

## Demo matrix (the 5 required, each: inject → alert visible → recover → resolved)

| Alert | Inject | Watch | Recover |
|---|---|---|---|
| WorkerDown + QueueBacklog | `fail-worker.ps1` | `alerts.ps1` shows both firing ≤3m | `recover-worker.ps1` → depth 0 |
| ApiDown | `fail-api.ps1` | ApiDown firing; `/healthz` still ok | `recover-api.ps1` |
| EhrFailing | `ehr-failure.ps1 -Mode unavailable` | EhrFailing firing ≤4m | `ehr-recover.ps1` |
| SecurityGateFailing | post `{"name":"gitleaks","ok":false}` to alert-api `/gates` (or run `ci.sh` with planted secret, M8) | SecurityGateFailing firing ≤2m | post `ok:true` / green gates |
| PostgresDown | `fail-db.ps1` | PostgresDown firing | `recover-db.ps1` |

`scripts/alerts.ps1` prints firing+pending from Prometheus plus the last
stored notifications — the single command an evaluator runs during a drill.
