# ARCHITECTURE

The single architecture document (§26 deliverable #1): system, boundaries,
security model, deployment, reliability, observability, failures, recovery,
decisions. Detail lives in the linked files; this is the map.

## System

Client → NGINX `:8080` (sole published port) → API `:8000` (DMZ, dual-homed)
→ internal net: AI `:8001`, EHR `:8002`, Redis (queue), PostgreSQL (state),
worker (no ports). Monitoring overlay (Prometheus `:9090`, Grafana `:3000`,
Alertmanager → alert-api) scrapes container-local `/metrics` on `internal`.
Canonical diagram: `./architecture.mmd` (same directory).

## Network boundaries

`edge` carries nginx+api; `internal` carries everything else; api is the only
dual-homed service. Proof: `test_compose_structure` (build-breaking) +
`scripts/net-audit.sh` (live negative test). Full why-per-service table:
`../NETWORKING.md`.

## Security model

Secrets via env (local `.env`, AWS Secrets Manager mirror) — never baked.
Least privilege: 5-role matrix, non-root, exec/task role split, SGs task-only.
Hardening: `cap_drop ALL` ×15, read-only ×11 (4 documented exceptions).
Full matrix + Finding M9-1: `../SECURITY.md`.

## Deployment

Verify-before-replace: candidate gated on `/ready` → switch via nginx
resolver TTL → smoke → retire old. Broken releases never get traffic;
post-switch failures auto-roll back. `../DEPLOYMENT.md`, `scripts/deploy.sh`.

## Reliability / failure scenarios / recovery

F1–F7 drills + 7 EHR modes + BREAK_READY; retries with backoff, fail-fast
auth, no-retry unknown outcomes. Backup/restore self-verify; recreation ≠
recovery. `../INCIDENTS.md`, `../RECOVERY.md`, `RESILIENCE_ANALYSIS.md`.

## Observability

One log schema (`evt()`), Prometheus metrics, `/health`+`/ready` dual-use,
11→15-panel Grafana dashboard, 10 alerts with operator contracts.
`../OBSERVABILITY.md`, `../ALERTING.md`.

## Technology decisions

36 decisions with rationale + trade-offs: `../DECISIONS.md`. Cost lens:
`../COST.md`. Cloud mapping: `CLOUD_MIGRATION.md`.
