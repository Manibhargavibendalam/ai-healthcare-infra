# SECURITY

## Trust boundaries

| Zone | Members | Reachable from |
|---|---|---|
| Public (edge) | NGINX ingress 127.0.0.1:8080 | operator/evaluator, host-local only |
| DMZ | API (edge+internal, no ports) | ingress only |
| Private (internal) | PostgreSQL, Redis, worker, AI mock, EHR mock | API/worker via internal network only |
| Ops-local | Grafana :3000, Prometheus :9090 (M3-obs) | 127.0.0.1 only, never LAN |

Enforced (M3), not claimed: only nginx has a `ports:` entry (`test_compose_structure`
fails otherwise); `bash scripts/net-audit.sh` proves it live (port maps,
edge-guest negative test vs db/redis, membership). Operator access to private
services is `docker compose exec` + `/scripts/svc.py`, never a socket.

## Secrets: never in code, images, compose, tfvars, CI, or git

- Local: gitignored `.env` (generated, alphanumeric, URL-safe) → env vars at runtime.
  `.env.example` holds placeholders only (unit-enforced: secret keys must start
  with `CHANGE_ME`). Compose/CI reference `${VAR}` — a literal value fails
  `test_no_secrets_in_compose_or_ci`.
- Proof: `gitleaks detect` → **no leaks found**; `git check-ignore .env` → ignored.
- Cloud path (same architecture, real deployment): `terraform/modules/security`
  creates ONE Secrets Manager JSON (`DATABASE_URL`, `REDIS_URL`); ECS tasks
  receive them as env vars at launch via the execution role; human operators
  pass values as `TF_VAR_db_password` / `TF_VAR_redis_auth_token` (CI secrets
  in the pipeline) — never in tfvars, images, or git. Local `.env` and remote
  Secrets Manager are the same pattern: values injected at runtime, never baked.

| Secret | Local | AWS (terraform/) |
|---|---|---|
| DB password | `.env` → compose env | `TF_VAR_db_password` → Secrets Manager → task env |
| Redis token | `.env` → compose env | `TF_VAR_redis_auth_token` → Secrets Manager → task env |
| Grafana admin | `.env` → compose env | out of scope (local ops UI only) |
| TLS cert | n/a (loopback) | `TF_VAR_alb_certificate_arn` (ACM) |

## If a container is compromised (blast-radius analysis)

Attacker in api container: sees only `internal` DNS (no host ports), runs as
`appuser` on a read-only filesystem, holds NO secret values (only env refs
injected at runtime), cannot reach the host or internet beyond the compose
network. Lateral movement needs another exploit: DB/Redis accept only
expected protocols, worker exposes no socket at all. Detection: error-rate
+ latency alerts, anomalous `api_db_errors_total`, audit log of mode changes.
Response: `docker compose kill + up -d <svc>` (immutable image, no local
state to preserve), rotate secrets if exfiltration is suspected, review
`ehr_syncs`/`jobs` for malicious rows. Read-only + dropped caps + non-root
exist precisely to make this scenario survivable.

## Least privilege: five roles, minimal permissions each

| Role | Gets | Explicitly denied | Where |
|---|---|---|---|
| Developer | repo read/write, run drills + `ci.sh`, read logs/metrics | `.env` values (gitignored, never shared), prod cloud creds, secret reads | git + compose |
| Deployment system (CI + `deploy.sh`) | build images, run gates, recreate `api` from verified tags, post `/deploys` | SSH/host access, DB writes, secret VALUES (only ARNs/refs) | `ci.yml`, `deploy.sh` |
| Infrastructure admin | `terraform plan/apply/destroy`, `TF_VAR_*` secrets in CI | app data access, everyday deploys | `terraform/` |
| Runtime services | api: DB+Redis+AI/EHR over internal net only; worker: same + no inbound at all | host, internet, each other's secrets,enamespaces beyond `internal` | compose networks, SGs |
| Monitoring | scrape `/metrics`, read logs, receive webhooks | write paths, deploys, secret values | overlay, alert-api |

Nobody is admin everywhere: developers can't deploy to cloud, CI can't read
secret values, tasks can't reach the internet, monitoring can't change anything.
AWS mirror: execution role (pull + read ONE secret) vs task role (zero extra
permissions); SGs allow DB/Redis **only** from ECS tasks.

## Validation matrix (evidence collected)

| Check | Where | Result |
|---|---|---|
| Secret detection | `gitleaks detect` (host, git mode) | ✅ no leaks |
| Deps HIGH/CRITICAL | `trivy fs services/` (exact `==` pins) | ✅ 0 vulns |
| Dockerfile misconfig | `trivy fs --scanners misconfig` | ✅ 0 findings |
| IaC syntax/types | `terraform validate` (dev + prod envs) | ✅ valid |
| IaC misconfig | `trivy fs terraform/` | ✅ 0 findings (6 fixed, 4 justified suppressions — see D24) |
| IaC policy | Checkov (CI-only: host App Control blocks its rustworkx DLL; Trivy misconfig is the local equivalent) | ✅ 0 via Trivy; Checkov in CI |
| Deps audit | pip-audit (host .venv, all 6 requirements files) | ✅ 0 vulns (found 18 → fixed, see D30) |
| Image scan | Trivy image (CI post-build; needs daemon — local equivalent is trivy fs + misconfig, both 0) | ✅ fs clean; image scan in CI |
| Gate blocks deploy | `ci.sh --demo-block` plants dummy secret → gitleaks FAILS → exit 1, no deploy; clean tree → exit 0 | ✅ proven live (see Finding M9-1) |

## Hardening checklist (per container)

Base for all: minimal pinned base · non-root user · `privileged` never set ·
`cap_drop: [ALL]` on EVERY service · no secrets baked into images
(runtime env only) · healthchecks · enforced `cpus`/`mem_limit` ·
`init:true` + SIGTERM draining · read-only seed/script mounts.
Policy is unit-tested (`test_container_hardening` fails the build on drift).

| Service | read-only | Why / exception |
|---|---|---|
| api, ai, ehr-mock, worker, alert-api, loadgen, api-candidate | ✅ + `tmpfs: /tmp` | logs→stdout, code in ro layers |
| nginx | ✅ + `tmpfs: /tmp,/var/cache/nginx,/run` | unprivileged image designed for this |
| postgres-exporter, node-exporter, alertmanager | ✅ + `tmpfs: /tmp` | static binaries, state in volumes |
| db, redis | ❌ (cap_drop only) | official images need writable runtime dirs beyond data volumes |
| prometheus, grafana | ❌ (cap_drop only) | TSDB WAL / sqlite+plugins need writes beyond data volumes |

Exceptions are an explicit test list, not an oversight — and every exception
carries a live-verify command for first boot (`docker compose exec <svc>
touch /probe && rm /probe` must SUCCEED on writable ones; hardening is
re-checked live by re-running the policy test's assertions against
`docker inspect`).

## Finding M9-1 — deliberate secret leak blocks the pipeline (DEMONSTRATED)

- Finding: dummy high-entropy credential planted as untracked `ci-plant-*.tmp`.
- Severity: critical (any merged secret = credential rotation incident).
- Detection: `bash scripts/ci.sh --demo-block` → gitleaks gate FAILS with
  `Fingerprint: ci-plant-3378.tmp:generic-api-key:1` → exit 1,
  `PIPELINE BLOCKED: 1 gate(s) red — no deploy`. The `api` image is never
  rebuilt, `deploy.sh` never runs.
- Impact of a MISS (had the gate not existed): secret enters git history,
  then image layers/CI logs — revocation across VRCS, registry, and secrets
  manager. The drill proves the miss cannot happen silently.
- Remediation: remove the file (drill trap does it automatically; verified:
  no `ci-plant-*` remains, `git status` clean) → re-run `bash scripts/ci.sh`
  → `PASS=7 FAIL=0`, exit 0.
- Verification evidence: fingerprints + exit codes above, reproducible via
  `DEMO_RUNBOOK.md` §8. Scanner-trust footnote: during this drill we caught
  OUR OWN config neutering gitleaks (see D32) — the gate is proven against a
  planted secret, not assumed from a green run.

## Finding D30 (prior, real) — 18 vulnerable dependencies fixed

pip-audit found 18 (requests + transitive starlette); fixed by version bumps
(`requests==2.33.0`, `fastapi==0.135.0`, `starlette==1.6.0`); compat proven by
48/48 tests; re-scans green on pip-audit AND Trivy. Full story in DECISIONS.md.
