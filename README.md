# Secure, Reliable & Scalable Cloud Infrastructure Simulation
## for an AI Healthcare Platform

This is an **infrastructure and operations** project, not a healthcare
application. The app layer (FastAPI API, AI mock, EHR mock, Python worker,
PostgreSQL, Redis) exists only to generate realistic behavior: traffic,
queue depth, retries, failures, deployments, metrics, and incidents.
Everything healthcare is synthetic and mocked.

Start with `REQUIREMENTS_TRACEABILITY.md` (what maps to what),
`DECISIONS.md` (why each choice), and `DEMO_RUNBOOK.md` (exact commands).

## Architecture (one picture)

```
browser/evaluator ──▶ NGINX :8080 (M2, controlled ingress, only public door)
                        │  edge net
                        ▼
                  API :8000 ──▶ internal net ──▶ AI :8001, EHR :8002 (mock external),
                        │                        Redis (queue), PostgreSQL (state)
                        │                        Worker (no ports at all)
                        ▼
                  Prometheus ◀ scrape ◀ /metrics · Grafana :3000 (M3) · alerts (M3)
```

Canonical diagram source: `docs/architecture.mmd` (mermaid — paste into
mermaid.live to render; ASCII twin in `NETWORKING.md`).

Trust boundaries: only the ingress is reachable. PostgreSQL, Redis, worker,
and AI mock publish **no host ports** and live on the internal network.
Secrets travel as environment variables from a gitignored `.env` (local) or
Secrets Manager (Terraform mirror). Containers run as non-root (`appuser`).

## Technology choices (one line each)

Python/FastAPI (small, health+metrics friendly) · PostgreSQL (durable state +
`pg_dump` recovery) · Redis lists (queue depth, blocking consume, atomic move)
· hand-rolled worker (~120 lines, fully explainable retry policy) · Docker +
Compose (reproducible local cloud) · NGINX (controlled ingress, blue/green flips)
· Terraform AWS mirror, validate-only, $0 (VPC/ALB/ECS/RDS/ElastiCache/ECR)
· GitHub Actions + local `ci.sh` mirror · pytest + Locust · Trivy/Gitleaks/
Checkov/pip-audit · Prometheus/Grafana/Alertmanager. Full rationale: `DECISIONS.md`.

## Local prerequisites

- Docker Desktop with running Linux engine (`docker version` shows `Server:`)
- Git + Git Bash (scripts) · Python 3.12 + venv (local unit tests)
- Zero host installs for scanners: Trivy/Gitleaks/Terraform via winget is
  enough; Checkov/pip-audit run in CI (need Python, covered by the venv).

## How to start / stop

```powershell
cd C:\Users\sunka\OneDrive\Desktop\ai-healthcare-infra
docker compose build
docker compose up -d
docker compose ps            # 5 healthy + worker running
docker compose down          # stop, keep data
docker compose down -v       # destroy everything incl. volumes (re-seeds on next up)
```

## How to test

```powershell
.\.venv\Scripts\python -m pytest tests/ -q     # foundation unit tests, no engine needed
bash scripts/m1-verify.sh                      # 8 end-to-end M1 tests vs live stack
```

## How to simulate failures

- EHR modes without restarts: `POST /mode` (`normal|slow|timeout|fail500|fail401|unavailable`) on :8002
- True connection-refused: `docker compose stop ehr`
- Worker down (queue buffers): `docker compose stop worker` → start again, watch drain
- DB down (readiness degrades): `docker compose stop db` → `GET /ready` → 503 naming postgres
- Full story per scenario: `DEMO_RUNBOOK.md`

## How to monitor (M3)

Prometheus scrapes `/metrics`; Grafana dashboard shows API health, queue depth,
worker rate, DB reachability; Alertmanager → alert-api webhook sink logs
actionable alerts. Today: `GET /metrics` + `GET /worker/status` already work.

## How to deploy (M4)

Blue/green through nginx: build candidate → wait `/ready` → flip upstream →
retire old. Broken candidate never gets traffic; `rollback.sh` flips back.
`bash scripts/deploy.sh v2` / `bash scripts/rollback.sh`.

## How to recover

- Recreate infra: `docker compose down -v && docker compose up -d` (minutes, code-only)
- Recover state: `bash scripts/backup.sh` (pg_dump) / `bash scripts/restore.sh` (M8)
- RPO/RTO, what is lost (Redis queue), RDS 7-day backups in TF: `RECOVERY.md`

## Costs: $0

Local runs free; Terraform mirror is validate-only (never applied). The one
deliberate cost call — no NAT gateway — is documented in `COST.md`.
