# LIVE DEMONSTRATION — 21-minute operational story

## PDF §33 phase map (PHASE → Step)

| PHASE(S) | Step(s) | PHASE(S) | Step(s) |
|---|---|---|---|
| 1 start env | 4 | 16 recover worker | 11 |
| 2 diagram | 2 | 17 drain + recovery | 11 |
| 3 boundaries | 3 | 18 EHR failure | 12 |
| 4 Terraform | §1 appendix + terraform/README | 19 timeout/retry metrics | 13 |
| 5 infra recreation | 20 | 20 recover EHR | 13 |
| 6 CI/CD | 14 (ci.sh) | 21 healthy deploy | 16–17 |
| 7 security validation | 14 | 22 broken deploy | 18 |
| 8 healthy deploy | 16 | 23 health failure | 18 |
| 9 readiness/health | 17 | 24 old version kept | 18 |
| 10 logs/metrics/Grafana | 5–7 | 25 rollback | 19 |
| 11 workload | 8 | 26 backup/recovery | 20–21 |
| 12 worker failure | 9 | 27 SPOFs | 22 + RECOVERY.md |
| 13 queue growth | 10 | 28 access/audit | 23 |
| 14 alert | 10 | 29 cost | 24 |
| 15 investigate | 10 | 30 cloud migration | docs/CLOUD_MIGRATION.md |
| | | 31 decisions | 25–26 |

One coherent run: healthy system → load → failure → recovery → blocked
release → safe release → recovery loop → books closed. Total 21 minutes;
each step lists command, expected output, what to watch, recovery, and
fallback. Shell: PowerShell + `curl.exe`, `bash` = Git Bash, repo root
`C:\Users\sunka\OneDrive\Desktop\ai-healthcare-infra`.
Precondition: Docker engine running (`docker version` shows `Server:`).

## ACT 1 — THE SYSTEM (0:00–0:05)

### Step 1 — Scope: infrastructure, not healthcare (0:00, 1 min)
Command: `Get-Content README.md | Select-Object -First 12`
Expect: infra/ops purpose statement. Watch: nothing yet — set the frame:
mock app exists to generate traffic, failures, deploys. Fallback: quote it.

### Step 2 — Architecture diagram (0:01, 1 min)
Command: `Get-Content docs/architecture.mmd` (+ open in mermaid.live)
Expect: edge/internal zones, 8 services, trust arrows. Watch: point at the
single `:8080` door. Fallback: ASCII twin in NETWORKING.md.

### Step 3 — Trust boundaries (0:02, 2 min)
Command: `Select-String -Path compose.yaml -Pattern 'ports:|networks:'`
Expect: ONE published port (nginx :8080); api dual-homed; rest internal.
Watch: narrate why DB/Redis/worker/AI are private (blast radius).
Recovery: n/a (static). Fallback: NETWORKING.md table.

### Step 4 — Start infrastructure (0:04, 1 min)
Command: `docker compose build; docker compose up -d; docker compose ps`
Expect: 7 services, 5 healthy + worker running. Watch: health-gated startup
order in `ps`. Recovery: `docker compose logs <svc>` on failure.
Fallback: `down -v` + retry (recreate is cheap — that's the point).

## ACT 2 — NORMAL OPERATION (0:05–0:08)

### Step 5 — Show the fleet (0:05, 1 min)
Command: `docker compose ps; docker network ls | Select-String 'edge|internal'`
Expect: containers + `edge`/`internal` networks. Watch: names match diagram.
Fallback: `docker ps` raw.

### Step 6 — E2E flow: client → API → Redis → worker → AI → EHR → DB (0:06, 2 min)
Command: `bash scripts/m1-verify.sh` (T1–T10, fail-fast)
Expect: `ALL M3 TESTS PASSED`; final job `completed`. Watch: `docker compose
logs worker | Select-String completed` shows cid-tagged lines; DB row flips
queued→completed. Recovery: script is fail-fast — fix, re-run.
Fallback: run T1–T5 by hand (single job lifecycle).

## ACT 3 — LOAD (0:08–0:10)

### Step 7 — Grafana dashboard (0:08, 1 min)
Command: open `http://127.0.0.1:3000` → "Healthcare Platform — Operations"
Expect: 11 panels green/baseline. Watch: request rate, queue depth flat.
Fallback: `curl :9090/api/v1/query?query=up` proves metrics flow.

### Step 8 — Increased workload + scaling (0:09, 1 min)
Command: `scripts\load-test.ps1 -Count 100; scripts\measure-workers.ps1 -WindowSec 30`
Expect: max_depth printed, drain to 0, jobs/sec rate. Watch: Grafana queue
tile spikes then drains; worker CPU in `docker stats`. Recovery: scale
workers (`scale-worker.ps1 -Count 3`) if drain is slow — that IS the demo.
Fallback: smaller `-Count 30`.

## ACT 4 — WORKER FAILURE (0:10–0:12)

### Step 9 — Stop worker (0:10, 30 s)
Command: `scripts\fail-worker.ps1`
Expect: STOPPED + depth ≥3 buffered. Watch: queue tile starts climbing.
Fallback: `docker compose stop worker` directly.

### Step 10 — Failure, alert, investigation (0:10, 1 min)
Command: `scripts\alerts.ps1; curl.exe -s :8080/worker/status`
Expect: WorkerDown firing (≤3m), `alive:false`, heartbeat aging.
Watch: Grafana queue + restarts tiles; `docker compose logs worker` ends
cleanly (gone, not wedged). Recovery: next step. Fallback: `LLEN` via exec.

### Step 11 — Restart + drain (0:11, 1 min)
Command: `scripts\recover-worker.ps1`
Expect: depth 0, jobs completed, heartbeat fresh, restarts +1.
Watch: metrics recovery on dashboard; alerts resolve. Fallback: manual start
+ poll `queue/stats`.

## ACT 5 — EHR FAILURE (0:12–0:14)

### Step 12 — EHR slow/unavailable (0:12, 30 s)
Command: `scripts\ehr-failure.ps1 -Mode unavailable`
Expect: mode set; jobs begin retrying. Watch: EhrFailing pending.
Fallback: `slow` mode (softer, still completes).

### Step 13 — Timeout/retry/failed/alert/recovery (0:13, 1.5 min)
Command: post probe job; `scripts\alerts.ps1`; `ehr-recover.ps1`
Expect: attempts=3 then failed; EhrFailing firing ≤4m; after recover, probe
completes attempts=1. Watch: `ehr_syncs` rows per attempt; backoff gaps.
Recovery: `ehr-recover.ps1`. Fallback: timeout mode (same story, slower).

## ACT 6 — SECURITY (0:14–0:16)

### Step 14 — Security validation (0:14, 1 min)
Command: `bash scripts/ci.sh` (runnable gates)
Expect: PASS=8 FAIL=0; gitleaks/trivy/pip-audit green. Watch: gate lines.
Recovery: n/a. Fallback: individual scanner commands from §1 reference.

### Step 15 — Intentional failure → blocked (0:15, 1 min)
Command: `bash scripts/ci.sh --demo-block`
Expect: `ci-plant-*.tmp:generic-api-key:1`, exit 1, PIPELINE BLOCKED; trap
removes plant (`git status` clean). Watch: NOTHING deploys — that absence is
the proof. Recovery: automatic (trap). Fallback: pre-captured log excerpt.

## ACT 7 — DEPLOYMENTS (0:16–0:19)

### Step 16 — Healthy v2 (0:16, 1.5 min)
Command: `bash scripts/deploy.sh v2`
Expect: candidate gated → switched → `DEPLOY OK`. Watch: readiness polls,
old containers removed only after success. Recovery: built-in gates.
Fallback: `v1` label (same path).

### Step 17 — v2 serving proof (0:17, 30 s)
Command: `curl.exe -s :8080/health` (version v2) + db/stats + probe enqueue
Expect: version match, deps ok, job accepted. Watch: Grafana deploy panel
(`api_build_info`). Fallback: `docker compose logs api`.

### Step 18 — Broken v3 blocked (0:18, 1 min)
Command: `bash scripts/deploy.sh v3 --broken`
Expect: exit 1; candidate destroyed; `/health` STILL v2; DeployFailed fires.
Watch: previous version serving under the failure — the whole point.
Recovery: automatic (api untouched). Fallback: narrate gate log.

### Step 19 — Rollback (0:19, 30 s)
Command: `bash scripts/rollback.sh`
Expect: re-pinned to prev, verified, history entry. Watch: version flips back.
Fallback: explicit `rollback.sh v1`.

## ACT 8 — RECOVERY + BOOKS (0:19–0:21)

### Step 20 — Infra recreation (0:19, 30 s)
Command: `docker compose down -v; docker compose up -d`
Expect: minutes-later all healthy, history empty. Watch: startup order.
Fallback: `measure-startup.ps1` timings.

### Step 21 — Backup/restore, not recreate (0:20, 1 min)
Command: `bash scripts/backup.sh` BEFORE down; `bash scripts/restore.sh` AFTER up
Expect: counts match `.counts`; probe completes. Watch: state returns ONLY
via restore — recreation alone left history empty. Fallback: document the
distinction from RECOVERY.md if time is short.

### Step 22 — Incidents (0:20, 30 s)
Command: open `INCIDENTS.md` INCIDENT-1/2
Expect: 9 fields + timelines narrated in 30s. Fallback: one incident only.

### Step 23 — Auditability (0:21, 30 s)
Command: `tail deployments.jsonl; tail ci-report.jsonl`
Expect: actor/version/gates on screen. Watch: 8-question matrix in
AUDITABILITY.md. Fallback: `git log --oneline`.

### Step 24 — Cost (0:21, 30 s)
Command: open `COST.md` model table
Expect: $0 posture + as-if-applied numbers in 30s. Fallback: one sentence
(validate-only, no NAT, lean sizes).

### Step 25 — Trade-offs (0:22, 1 min)
Command: narrate 3 (compose-vs-k8s, hand-worker vs RQ, resolver vs static)
Expect: each names what was given up (D33/D26/D2). Fallback: DECISIONS.md.

### Step 26 — Coverage close (0:23, 1 min)
Command: `pytest tests/ -q` (68→70 live count) + traceability verdict line
Expect: green suite as the final screen. End: "14 COMPLETE, rest staged on
one blocker" + audit files named. Fallback: `git log --oneline`.

## STEPS 27–31 — RESERVED FLEX (0:24+)
Deep-dives if asked: SPOF table (RECOVERY.md), D32 scanner story,
BREAK_READY vs F7, queue math, TF module tour. Each ≤1 min, any order.

## APPENDIX — command reference (all acts, copy-paste)

### A. Foundation (no engine)
```powershell
.\.venv\Scripts\python -m pytest tests/ -q
bash -n scripts/*.sh (each)
docker compose config --quiet
gitleaks detect --source . -v
trivy fs --scanners vuln,misconfig --severity HIGH,CRITICAL --no-progress services/
terraform -chdir=terraform/environments/dev init -backend=false; terraform -chdir=terraform/environments/dev validate
terraform -chdir=terraform/environments/prod init -backend=false; terraform -chdir=terraform/environments/prod validate
```

### B. E2E + boundaries
```powershell
docker compose build; docker compose up -d; docker compose ps
bash scripts/m1-verify.sh
bash scripts/net-audit.sh
Test-NetConnection 127.0.0.1 -Port 5432   # must FAIL
Test-NetConnection 127.0.0.1 -Port 8080   # must SUCCEED
```

### C. Drills (F1–F7 pairs print next steps; full lifecycles: INCIDENTS.md)
```powershell
# powershell -ExecutionPolicy Bypass -File prefix for .ps1
# fail-worker/recover, fail-api/recover, fail-db/recover, ehr-failure/recover,
# fail-service/recover -Service ai, fail-config/recover, load-test -Count 100
```

### D. Scale + measure + observe + alerts
```powershell
scripts\scale-api.ps1 -Count 3; scripts\measure-api.ps1 -Mode jobs -Requests 200 -Concurrency 10
scripts\scale-worker.ps1 -Count 3; scripts\measure-workers.ps1 -WindowSec 30
docker compose -f compose.yaml -f compose.monitoring.yaml up -d
scripts\alerts.ps1
```

### E. Deploy + CI + recovery + audit
```powershell
bash scripts/deploy.sh v2; bash scripts/deploy.sh v3 --broken; bash scripts/rollback.sh
bash scripts/ci.sh; bash scripts/ci.sh --demo-block
bash scripts/backup.sh; bash scripts/restore.sh backups/manual-<ts>.sql
git log --oneline; Get-Content deployments.jsonl; Get-Content ci-report.jsonl
```
