# CI/CD

13 stages across 10 jobs (`.github/workflows/ci.yml`); local mirror
`../scripts/ci.sh` runs the same gates without pushing.

## Stage map

1 Checkout (every job) · 2 Deps (setup-python/pip per job) · 3 Tests
(`lint`+`test`+`integration`: ruff, 71 pytest, live `m1-verify.sh` +
`net-audit.sh` on runner Docker) · 4 Validation (ruff policy, pyproject)
· 5 Secrets (gitleaks blocks on any hit) · 6 Deps (pip-audit, all 6 files)
· 7 IaC (fmt + dev/prod validate + Checkov) · 8 Build (`API_TAG=ci`)
· 9 Image scan (Trivy CRITICAL on api+worker) · 10 Deploy (main only,
`deploy.sh $SHA`) · 11 Verify (ready/health/version/db/probe)
· 12 Release (second deploy proves controlled shift) · 13 Rollback drill
(rollback.sh + old-serves-again) → `audit` job (step-summary + artifacts,
always runs).

## Gate discipline

Every job before `build` blocks via `needs`; release is main-only; a red
gate means no deploy — PROVEN live (`ci.sh --demo-block` → exit 1 with
`ci-plant-*.tmp:generic-api-key:1`, trap-cleaned; clean tree → exit 0).
Finding report: `../SECURITY.md` → Finding M9-1.

## Auditability

Per run: commit, actor, per-stage results, `deployments.jsonl` artifact.
Locally: `ci-report.jsonl` appended per run. Matrix: `../AUDITABILITY.md`.
