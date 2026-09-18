# REQUIREMENTS TRACEABILITY (PDF §§1–34)

Exact columns: PDF Section | Requirement | Implementation | Files |
Test/Scenario | Evidence | Status (PASS/PARTIAL/FAIL).
PASS = executed evidence, no daemon needed. PARTIAL = implemented +
policy-tested, live run pending (engine down all session). FAIL = none.
Structure note (§3): canonical docs live at repo root (tests + runbook
reference them); `docs/` holds the 7 syntheses with no root equivalent.
`docs/ARCHITECTURE.md` maps every overlapping name to its canonical file.

| PDF Section | Requirement | Implementation | Files | Test/Scenario | Evidence | Status |
|---|---|---|---|---|---|---|
| 1 Core objective | prod-like local sim, 15 evaluator abilities | full stack + runbook | compose*.yaml, DEMO_RUNBOOK.md | §1 foundation tests | 71 pytest pass | PARTIAL |
| 2 Strategy | lean stack, no k8s/kafka/mesh | compose+TF mirror, 6 services | DECISIONS.md D1/D11/D26 | test_compose_structure | no k8s manifests exist | PASS |
| 3 Structure | clean repo, separated concerns | services/infra/scripts/tests/docs + root docs | repo tree | test files-exist (foundation) | `ls` inventory 20 commits | PASS |
| 4 Platform | api/ai/worker/postgres/ehr + endpoints | FastAPI mocks, 7 EHR modes, /version + /admin/mode + /ehr/sync aliases | services/*/app/main.py | 30+ unit tests (modes/matrix/ready) | pytest green | PARTIAL |
| 5 Queue | Redis backlog/retry/fail + 6 named metrics | lists + delay ZSET + `worker_processing_seconds` added | services/worker/worker.py | queue-math/backoff tests, T2–T9 scripted | pytest green | PARTIAL |
| 6 Network | edge/internal, private DB/redis/worker/AI | no published ports except :8080; negative-test script | compose.yaml, NETWORKING.md | test_compose_structure, net-audit.sh | config valid | PARTIAL |
| 7 IaC | reproducible TF, dev+prod, full lifecycle docs | 6 modules, thin envs, README lifecycle | terraform/ | fmt/validate/fmt-check + layout tests | dev+prod valid | PARTIAL |
| 8 Environments | dev + prod-like, shared defs | identical module calls, tfvars-only diffs | terraform/environments/ | validate both, diff-able | both valid | PASS |
| 9 Security arch | network + least-privilege (5 roles) | SGs, 5-role matrix, exec/task split | SECURITY.md, TF security/ | policy tests | gitleaks clean | PARTIAL |
| 10 Secrets | zero hard-coded; env + scans + cloud map | .env ignored, placeholders enforced, Secrets Manager wired | .env.example, TF security/ | 4 sweep tests + gitleaks | clean, exit 0 | PASS |
| 11 Containers | non-root, minimal, pinned, read-only, caps, limits | slim pins, USER appuser, cap_drop×15, ro×11 | Dockerfiles, compose* | hardening + pin tests, trivy 0 | trivy ZERO | PARTIAL |
| 12 Infra sec validation | automated, actionable, report | gitleaks/trivy/checkov/pip-audit gates | ci.sh, ci.yml, SECURITY_REPORT.md | ci.sh executed (blocks) | PASS=8 + BLOCK exit 1 | PARTIAL |
| 13 CI/CD | 16 stages, gates before deploy, failing demo | 13 stages/10 jobs + mirror; insecure change blocked | ci.yml, ci.sh | ci.sh PASS + BLOCK runs | exit 0 / exit 1 logs | PARTIAL |
| 14 Deploy | versioned, 9-step + 7-step failure paths | candidate gate, switch, smoke, auto-rollback | deploy.sh, rollback.sh, DEPLOYMENT.md | gate-order/refusal tests | policy green | PARTIAL |
| 15 Reliability | 8 failure modes, graceful degradation | retries, isolation, timeouts, degradation paths | worker.py, api, INCIDENTS.md | classify/backoff/degrade tests | pytest green | PARTIAL |
| 16 Scalability | independent api/worker scale, measured p50/p95/p99 | resolver LB, scale scripts, measure.py, locust | nginx.conf, scripts/, SCALING.md | percentile unit tests | math green, numbers pending | PARTIAL |
| 17 Observability | logs/metrics/health/dashboard (15 tiles) | evt() schema, prom exposition, 15-panel JSON | services, monitoring/ | schema/metric/dashboard tests | 15 panels validated | PARTIAL |
| 18 Alerting | 9 alerts + 4-field operator docs | 10 rules, AM grouping, webhook sink, viewer | alert.rules.yml, ALERTING.md | contract + metric-ref tests | 10 rules parsed | PARTIAL |
| 19 Incidents | 2+ incidents, 7-step lifecycle, 1 in detail | INCIDENT-1/2 (9 fields + timelines) + F1–F7 | INCIDENTS.md, INCIDENT_REPORT.md | structure tests | reports written | PARTIAL |
| 20 Backup/recovery | backup/restore/recreate/state + RTO/RPO targets | self-verifying scripts, counts compare | backup.sh, restore.sh, RECOVERY.md | content tests, bash -n | scripts sound | PARTIAL |
| 21 SPOF | 7 systems × 8 fields, honest limits | RESILIENCE_ANALYSIS.md + RECOVERY.md table | docs/RESILIENCE_ANALYSIS.md | coverage test | table complete | PASS |
| 22 Access/audit | 5 roles + 7 audit questions + cloud map | ACCESS_AND_AUDIT.md + AUDITABILITY.md + actor chain | docs/, deploy.sh actor | structure tests | matrices complete | PARTIAL |
| 23 Cost | 7 analyses, no invented bills | model + buckets + 12 techs + tensions + delta | COST.md (+docs map) | coverage tests | doc complete | PASS |
| 24 Scenarios | 7 scenarios × 8 required fields | runbook steps + F/EHR/load/deploy scripts | DEMO_RUNBOOK.md, scripts/ | narrative policy test | 26 steps + appendix | PARTIAL |
| 25 Tech selection | 16 techs × 5 fields | DECISIONS.md (36) + COST.md table | DECISIONS.md | coverage implied | 16/16 present | PASS |
| 26 Deliverables | 8 items incl. ONE diagram | docs/ARCHITECTURE + reports + runbook + .mmd | docs/, *.md, diagrams/ | diagram + structure tests | files exist | PARTIAL |
| 27 Not required | no frontend/AI/real data/cloud | none built (verified: no UI dirs, synthetic seed) | repo tree | seed-synthetic test | no violations | PASS |
| 28 Boundary | simulated vs engineered split | mocks thin, effort in infra (this repo's shape) | DECISIONS.md D2 | — (structural) | 20 commits show it | PASS |
| 29 Thinking | Q&A answered w/ evidence | per-area answers across docs | all docs | policy tests | static answers | PARTIAL |
| 30 Strong submission | 17 characteristics | each implemented (see rows above) | all | 78 tests | green | PARTIAL |
| 31 Weak prevention | 15 anti-patterns absent | policy tests for exposure/secrets/gates/health | tests, ci.sh | hardening/sweep/gate tests | green | PARTIAL |
| 32 AI assistance | AI_ASSISTANCE.md + accepted/changed/rejected | AI_ASSISTANCE.md + D15 | AI_ASSISTANCE.md | disclosure test | file complete | PASS |
| 33 Demo | 31 phases, coherent story | DEMO_RUNBOOK.md + phase map | DEMO_RUNBOOK.md | narrative test | 26 steps + flex | PARTIAL |
| 34 Audit | this table + 34 answers + fix loop | this file + FINAL_REQUIREMENTS_AUDIT.md | both | counts verified | artifacts complete | PASS |
