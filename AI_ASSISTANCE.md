# AI ASSISTANCE (PDF §32)

## Where AI helped

- Architecture exploration: network segmentation options, blue/green without
  orchestrator, queue-vs-broker choice.
- Implementation: service skeletons, worker loop, scripts, Terraform modules,
  dashboard JSON, CI workflow drafts.
- Troubleshooting: SG reference cycle, gitleaks-config neutering, pin
  conflicts (fastapi/starlette caps).
- Documentation: runbooks, reports, traceability scaffolding.
- Security review: scanner selection, hardening checklist, gate design.

## Suggested → accepted / changed / rejected

- Accepted: compose overlays, candidate-deploy pattern, JSONL histories,
  explicit-path gitleaks scanning.
- Changed: worker retries (immediate→backoff set), TF layout (flat→6 modules),
  lint scope (full ruff→E/F/I/UP/W with documented exclusions).
- Rejected: Kubernetes, Kafka, RQ/Celery, committed demo branch with a secret
  (taints history — untracked-plant drill instead), `ruff format` enforcement
  (churn without safety gain).

## Verification (candidate-owned)

68→71 pytest executed, ruff/compose/gitleaks/trivy/pip-audit/terraform
executed, ci.sh PASS + BLOCKED runs executed. No AI claim ships without a
test or scan result in REQUIREMENTS_TRACEABILITY.md. The candidate remains
responsible for architecture, correctness, security, testing, failure
analysis, deployment, and operations.
