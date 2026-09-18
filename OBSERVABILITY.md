# OBSERVABILITY (M6)

One schema for logs, one pull path for metrics, one dashboard for the operator.
Alerts are NOT in this milestone (dedicated alerting milestone next); the
metrics below are chosen so every future alert has a query ready.

## Logs: one schema everywhere

`evt()` (api/ai/ehr) and `log()` (worker) emit a single JSON schema:

```
ts | level | svc | cid | op | job_id? | status? | duration_ms? | dependency? | error? | extras…
```

- `ts` UTC ISO, `level` info/warning/error, `svc` api/ai/ehr/worker.
- `cid` = end-to-end correlation (`X-Request-ID`); `job_id` on job paths.
- `op` names the operation (`http`, `sync`, `process`, `ai_enrich`,
  `mode_change`, `start/retry/failed/completed`, `ready`, `db_stats`).
- `dependency` names the downstream (`postgres`, `redis`, `ai`, `ehr`).
- `error` truncated to 300 chars; `/ready` responses stay up/down only.

Trace one job: `docker compose logs | grep <cid>` spans api → queue →
worker → EHR/AI → Postgres. Mode changes log as warnings (security events:
who flipped a failure injector and when). Deploy/infra events land in the
same stream via compose (`up`, `stop`, health transitions).

## Metrics: what answers what

| Need | Metric | Source |
|---|---|---|
| API rate/errors/latency/active | `api_http_requests_total`, `api_http_request_duration_seconds`, `api_http_active_requests` | api `/metrics` |
| API availability | `up{job="api"}` + `/ready` | Prometheus + healthcheck |
| Jobs processed/failed/retried | `jobs_processed_total`, `jobs_failed_total`, `jobs_retried_total` | worker `:8003/metrics` |
| Processing latency (avg, not just last) | `job_processing_ms_sum / job_processing_count` | worker |
| Queue depth/delayed | `queue_depth`, `delayed_jobs` | worker |
| Worker restarts/uptime | `worker_restarts_total` (Redis INCR), `worker_uptime_seconds` | worker |
| DB reachability/latency/connections | `pg_up`, `pg_stat_activity_*`, `/api/v1/db/stats` | postgres-exporter + api |
| EHR count/failures/timeouts/latency/state | `ehr_sync_requests_total`, `ehr_sync_failures_total`, `ehr_sync_timeouts_total`, `ehr_sync_duration_seconds`, `ehr_mode_ok` | ehr `/metrics` |
| AI latency/failures | `ai_process_duration_seconds`, `ai_requests_total`, `ai_mode_ok` | ai `/metrics` |
| CPU/memory saturation | `node_cpu_seconds_total`, `node_memory_*` | node-exporter |
| Deployment version/health | `api_build_info{version}` + `up` | api `/metrics` |
| Deployment status/duration/failed | deploy-script events (next milestone: emit + log) | `scripts/deploy.sh` (staged) |

## Alerts (M7): Prometheus → Alertmanager → alert-api

Rules in `monitoring/prometheus/alert.rules.yml` (10 alerts, thresholds mirror
Grafana); Alertmanager groups by alertname and webhooks to `alert-api:8080/alerts`
(JSONL + counters + `GET /alerts`). Gate/deploy signals (`/gates`, `/deploys`)
feed the SecurityGateFailing and DeployFailed rules. Full contract per alert
+ noise policy + demo matrix: `ALERTING.md`. Viewer: `scripts/alerts.ps1`.

## Health: liveness vs readiness

- `/health` = "process alive" (always 200 while running; worker adds uptime).
- `/ready` = "safe to serve" (deps checked: postgres/redis for api+worker,
  mode for ai/ehr). Compose `depends_on: service_healthy` gates startup
  order; the deploy gate (next milestone) polls `/ready` before shifting
  traffic. Same endpoints serve ops monitoring AND deploy validation.

## Dashboard: `monitoring/grafana/dashboards/healthcare.json`

Provisioned as code (datasource + provider YAML); 11 panels answer the 11
questions in order, with thresholds (error %>5 yellow/>20 red; p95 >1s red;
queue >20 yellow/>100 red; restarts delta ≥1 red; saturation 80/95).
Open: `http://127.0.0.1:3000` (admin / `$GRAFANA_PASSWORD`, default `admin`).

## Start/stop

```powershell
docker compose -f compose.yaml -f compose.monitoring.yaml up -d
docker compose -f compose.yaml -f compose.monitoring.yaml ps
curl.exe -s http://127.0.0.1:9090/-/healthy
```
Stop: same files with `down` (add `-v` only to wipe prom/grafana data too).
