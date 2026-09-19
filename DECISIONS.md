# DECISIONS (M2 — additions D16–D20; D1–D15 unchanged from M1)

## D15 — AI assistance disclosure (PDF §31; written at final audit)
An AI coding assistant generated first drafts of scaffolding, service
skeletons, scripts, and docs across M1–M13. The candidate (owner) then:
reviewed every file line-by-line; fixed real bugs the drafts contained
(SG reference cycle, gitleaks-config neutering, scanner-divergent pins,
over-strict test policy); executed ALL verification in this repo (68
pytest, ruff, compose configs, gitleaks, trivy, pip-audit, terraform
validate, ci.sh PASS + BLOCKED runs); and wrote the failure analyses,
triage decisions (D24/D30/D32), and incident reports from observed outputs.
No AI-generated claim ships without a corresponding test or scan result in
REQUIREMENTS_TRACEABILITY.md. Live-runtime verification remains the
candidate's open duty (engine-gated items) — see FINAL_REQUIREMENTS_AUDIT.md.

## D16 — Exponential backoff via Redis delay set, not sleep
Retry waits 2s, 4s, 8s… (cap 30) using a `jobs:delayed` sorted set
(score = due epoch); each loop promotes due items to the live queue.
Why not `time.sleep` in the worker: sleeping blocks ALL jobs behind the
failing one; the delay set keeps the worker draining everything else.
Pure `retry_delay()` is unit-tested; T7 asserts elapsed ≥ 2+4s live.

## D17 — UNKNOWN_OUTCOME never auto-retries
EHR `unknown` returns HTTP 200 with `outcome=unknown`: the request may have
applied. Worker records `failed` with a reconciliation-required error and
attempts stays 1. Retrying could double-apply (e.g., double booking);
dropping would hide work. Distinct terminal state is the honest answer —
`classify()` encodes it, T9 proves attempts==1.

## D18 — One correlation id end-to-end (client request id = job id)
`X-Request-ID` in → reused, else generated → stored as `jobs.correlation_id`
→ envelope → `X-Request-ID` header to EHR/AI → every log line. No separate
request/job/span ids: one id an operator can grep across api, queue, worker,
AI, EHR, and both DB tables. Middleware shape duplicated per service
(deliberate: independent deploys, no shared lib to version).

## D19 — Migrations as numbered idempotent SQL + initdb mount
`db/migrations/001–003` mount into `initdb.d` for fresh volumes (alphabetical
= order) AND apply via `scripts/migrate.sh` on live DBs (tracked in
`schema_migrations`). Idempotency (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`,
explicit seed ids) makes both paths safe to re-run. Schema changes ship
separately from code — the deploy-step story.

## D20 — Appointments call AI synchronously, with degradation
`POST /api/v1/appointments` asks AI `/process` for a risk flag (timeout 3s);
any AI failure → booking still succeeds with `risk=null, ai_degraded=true`.
Rationale: demonstrates the sync internal path AND graceful degradation in
one endpoint (T10 kills the AI container to prove it). The async job path
(API→worker→AI) stays the primary AI consumer.

## D24 — Scanner triage: fix what you can, suppress with justification (M3)
Repo-wide `trivy fs` surfaced 10 IaC/container findings; all closed with
evidence, none ignored silently. FIXED: Dockerfile USER (explicit
`USER nginx`), ECR `IMMUTABLE` tags, ALB drop-invalid-headers, ALB 443/TLS13
+ :80→:443 redirect, SG egress restricted to ports, RDS IAM auth, VPC Flow
Logs module. One real bug found en route: mutual SG reference = Terraform
cycle — fixed with a standalone `aws_security_group_rule`. SUPPRESSED with
in-code justification: public ALB + public subnets (the design), task
HTTPS/DNS egress (no NAT by cost choice), dev deletion-protection off (prod
enforces via tfvars). Suppression syntax learned live: `tfsec:` short codes
inside blocks for attribute checks, `trivy:ignore:AVD-*` ABOVE the resource
for resource-level checks. Re-scan: ZERO findings.

## D25 — Failure drills as PowerShell scripts + resilience by construction (M4)
Drills ship as `.ps1` (operator's shell) with fail/recover pairs that print
their own verification: stop worker → queue buffers; stop api → ingress alive
but 502 (distinction proven, not assumed); stop db → 503 without crash AND
worker stays alive via loop-level requeue (F4 fix: DB errors previously
propagated out of `handle()` and would have killed the process); bad
`EHR_URL` override → safe retries, no loss; `load-test.ps1` measures
enqueue/drain rates against the new `GET /api/v1/queue/stats` (depth, delayed,
oldest age = live queue latency). Malformed numbers fail fast via `_num()`
with `invalid VAR=...` instead of a bare traceback. Every failure documented
Failure→…→Prevention in `INCIDENTS.md`; script presence + queue math +
env validation are pytest-covered.

## D26 — Measurement honesty + the nginx resolver (M5)
No performance number is claimed without its command (`SCALING.md` holds a
PENDING table, not results). Client-side measurement (`measure.py`, stdlib
only, threaded, unit-tested percentiles) is free and honest about loopback
noise; server histograms stay the dashboard source later. The scaling gotcha
found by reading, not running: a static nginx upstream resolves `api` ONCE
and pins to one replica, so `--scale api` would silently NOT balance —
fixed with `resolver 127.0.0.11` + variable (which M-deploy blue/green will
reuse for flips). Workers need nothing: the shared queue is the balancer.
Locust ships as a compose `loadgen` profile (never autostarts); burst shape
is a CLI override (`-u 100 -r 20`), not a code branch.

## D27 — Observability: one log schema, pull metrics, dashboard as code (M6)
Logs: `evt()`/`log()` with ts/level/svc/cid/op always present — `grep <cid>`
traces one job across all four services, no log aggregator needed locally.
Metrics: close the gaps the brief names (active requests, build info, DB
errors, AI/EHR latency histograms + mode gauges, worker sum/count for true
averages) rather than adding new systems; `outcome_for()` makes the EHR
contract unit-testable independent of HTTP. Monitoring is an OVERLAY file (M7 adds Alertmanager + alert-api to the same overlay)
(base stack untouched; exporters publish zero host ports; Grafana/Prometheus
host-local only). postgres-exporter gives real `pg_up` (not just our probe);
node-exporter covers host saturation. Deployment status/duration metrics are
explicitly deferred to the deploy milestone — the dashboard's panel 10 uses
`api_build_info` today and the doc says so.

## D21 — Segmentation via compose networks, proven by negative test
`edge` carries nginx+api; `internal` carries everything else; api is the only
dual-homed service. Proof is not documentation: `net-audit.sh` attaches a
throwaway container to `edge` and asserts `api:8000` answers while
`db:5432`/`redis:6379` time out. Policy is also unit-tested
(`test_compose_structure` fails the build if anyone publishes the DB).

## D22 — Operator access via exec channel, not ports
ai/ehr-mock/worker expose nothing, so drills use
`docker compose exec <svc> python /scripts/svc.py …` (scripts mounted
read-only). Same privilege model as `kubectl exec`: shell access is audited
and leaves with the container, unlike a published port that anyone on the
host can reach. E2E (T1–T10) still passes — through the ingress.

## D23 — Limits that are actually enforced + graceful everything
`cpus`/`mem_limit` (honored by plain `docker compose up`; `deploy.resources`
is the swarm translation, documented not used). `init:true` fixes PID-1
signal delivery; worker traps SIGTERM/SIGINT to drain (finish current job,
take no new ones); uvicorn handles SIGTERM natively; postgres/redis images
already shut down cleanly. Deterministic startup = depends_on health gates +
`restart:unless-stopped`.

## D28 — Alerting: rules as contract, webhook sink, gates as metrics (M7)
Rules carry the operator contract IN the file (expr + for + severity +
summary/description/cause/action/verify annotations) so `ALERTING.md` and
Prometheus can never disagree. One tier per condition + `for:` durations +
grouping + 4h repeat = the noise policy, enforced by config not discipline.
CI/deploy signals become METRICS via alert-api (`security_gate_ok`,
`deploy_failed_total`) because Prometheus can only alert on what it scrapes;
alerting anywhere else would split the operator's world in two. alert-api is
deliberately tiny (FastAPI + JSONL log, internal-only); its in-memory gauges
are a stated limitation that CI refreshes every run.

## D29 — Deploy: verify-before-replace, history as JSONL, rollback that refuses (M8)
No orchestrator, so blue/green is a candidate service + two gates: the new
image only becomes `api` after IT passes `/ready`, and traffic only counts
as moved after the ingress path proves ready. The M5 resolver (5s TTL) is
what makes the switch work — M8 reuses it instead of adding machinery.
History is JSONL (grep/cut only, no jq/python dependency in the hot path);
rollback refuses empty history rather than guessing. A failed release posts
`/deploys{failed}` so the DeployFailed alert fires with zero extra wiring —
the M7 alert-api design pays off here. CI's deploy job is one line because
all policy lives in the script, which is also what the evaluator runs by hand.

## D32 — Prove the scanner, don't trust it (M9 block-demo war story)
The drill caught THREE of our own mistakes before proving anything: (1) the
documented AWS EXAMPLE key is allowlisted by gitleaks — a realistic dummy is
required; (2) a `.gitleaks.toml` allowlist SILENTLY DISABLES all default
rules in gitleaks v8 (any config → zero findings; verified by isolation
tests) — so the config was deleted and the gate scans explicit paths
instead, guarded by a unit test forbidding the file's return; (3) the drill
script contained its own dummy literally and tripped the gate on itself —
fixed by storing the value split. Only after all three did the gate catch
exactly `ci-plant-3378.tmp:generic-api-key:1` with exit 1, then pass clean
with exit 0. A green scan you haven't attacked is decoration; this one survived
contact with a real (dummy) secret.

## D33 — Thirteen stages, ten jobs: release shares one stack (M10)
Stages 10–13 (deploy, verify, rollback) live in ONE `release` job because
separate jobs land on fresh runners with no Docker stack — splitting them
would be theater, not engineering. The rollback drill deploys twice, rolls
back, and asserts the old version serves, with zero source patching (a
broken-image drill would need sed-hacks into the tree; the block path is
already proven by deploy.sh's gate + the M9 secret drill). Lint policy keeps
E/F/I/UP/W and documents why BLE/SIM are excluded: bare `except` is our
resilience pattern, and a linter must never make failure handling worse.
`/health` now reports the release version (`API_VERSION` from the deploy),
so "verify expected version" is one curl, not an inference.

## D34 — Broken releases via env injector, smoke scoped to api-owned checks (M11)
`BREAK_READY=1` fails `/ready` the way `EHR_MODE` fails syncs: failure
injection WITHOUT source patching, consistent across the project. The v3
drill is therefore `deploy.sh v3 --broken` — one flag, fully repeatable.
Smoke deliberately covers only api-owned checks (version match, db/stats,
enqueue accepted); asserting full job COMPLETION would couple the deploy to
worker liveness and roll back good releases for worker outages. Post-switch
failures auto-run `rollback.sh` inline (the script recovers, not just
reports). Version rides in response + every log line + `api_build_info`:
three independent witnesses that the release serving is the release claimed.

## D37 — First live boot caught 6 blind spots (all fixed, all verified live)
Static review missed what one `up` exposed: (1) `cap_drop: ALL` kills
gosu/setpriv entrypoints (postgres exit 1, redis exit 127) — dropped the
drop for official images, kept containment via no-ports+private-net;
(2) redis healthcheck used an env var never injected into the container
(empty password → WRONGPASS) — added runtime-only `environment:`;
(3) EHR mode in process-global diverged across 2 uvicorn workers — moved to
a shared file in tmpfs; (4) Git Bash rewrites `/container/paths` for
docker.exe — `MSYS2_ARG_CONV_EXCL='*'` in all .sh files; (5) scripts said
`ehr-mock`, compose service is `ehr` — fixed every service-position ref;
(6) net-audit assumed `0.0.0.0` output and `docker compose port` semantics —
now asserts host-local binding via `PortBindings` inspect. Proof the fixes
hold: T1–T10 `ALL M3 TESTS PASSED (49 checks)` + `NET AUDIT PASSED (9 checks)`.

## D35 — Recovery is two loops; incidents are reports, drills are definitions (M12)
Backup and restore VERIFY themselves (pre-counts, COPY markers, size floor,
count comparison) because an unverified backup is a hope, not a control —
and recreation vs recovery stay separate commands for separate concerns
(`down -v/up` rebuilds code in minutes; only restore brings back data).
RTO/RPO are labeled DESIGN TARGETS until measured live; the SPOF table names
a remaining limitation per system instead of pretending any of them away.
INCIDENT-1/2 are written as replayable reports (commands + queries +
expected outputs + PENDING-ENGINE evidence slots); F1–F7 remain the drill
catalog. Every audit question resolves to one file + one command, and the
deploy actor is recorded with a fallback chain (explicit env → CI actor →
git user → whoami) so `who` is never empty.

## D36 — Cost is a design input, not an appendix (M13)
Every technology row names what was GIVEN UP, and the five-way tensions use
this repo's own examples (pooler vs simplicity, replicas vs bill, read-only
vs live-verify effort) instead of generic maxims. The $0 posture is a
constraint that shaped real choices (no NAT, lean sizes, validate-only TF),
each with a named prod upgrade path — under-spends are deliberate and
reversible, never accidental gaps an evaluator has to discover.

## D30 — pip-audit found 18 real vulns; fixed by bumping, proven by tests (close-out)
`pip-audit` over all 6 requirements files found 18: `requests==2.32.3`
(→2.33.0) and transitive `starlette 0.41.3` via FastAPI (14 issues, fixes up
to starlette 1.3.1). Trivy had reported 0 — different DBs disagree, which is
exactly why the brief demands BOTH scanners. Fix: `requests==2.33.0`,
`fastapi==0.135.0` (first line whose starlette floor is unbounded, allowing
1.x; 0.115.6 capped starlette <0.42 so no pin could help) + explicit
`starlette==1.6.0`. Chose 0.135.0 over latest 0.141.1 to shrink breakage
surface. Proof is engine-free: all 48 TestClient tests pass on the new stack
(the two new warnings are upstream anyio/starlette deprecations, not our
code). Re-scan: pip-audit 0, Trivy still 0. Checkov stays CI-only: this host's
Application Control policy blocks its rustworkx DLL at import — environment
restriction, documented, with Trivy misconfig (ZERO findings) as the local
IaC-policy evidence.

## D31 - Six modules, not four: split along blast radius (M8-IaC)
`data` became `database` + `queue` (RDS loss vs queue loss are different
recovery stories — one module per story) and `app` became `compute` +
`security`-owned identity/secrets + `monitoring`-owned log group (compute
receives roles, secret ARN, and log group NAME as inputs and owns none of
them). Environments only pass different tfvars over identical module calls.
`plan/apply/destroy` are documented with the creds they need and the data
warning destroy deserves; the local destroy→recreate→verify loop stays
`compose down -v / up / verify scripts`, with state recovery a separate,
explicit step.
