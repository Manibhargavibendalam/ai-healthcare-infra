# AUDITABILITY (M12)

Every operational question below has ONE primary evidence location plus the
exact command. Nothing relies on memory or chat history.

| Question | Evidence | Command |
|---|---|---|
| Who initiated a deployment? | `actor` field in `deployments.jsonl` (git config user → `$USERNAME` → `GITHUB_ACTOR` fallback chain; `DEPLOY_ACTOR` overrides) | `tail -n 5 deployments.jsonl` |
| What version was deployed? | `version` field in `deployments.jsonl` + `/health` + `api_build_info` | `curl -s :8080/health` |
| What infrastructure changed? | git history (code) + `terraform plan` output (cloud) + compose diff | `git log --oneline -- terraform/ compose*.yaml` |
| What security checks ran? | `ci-report.jsonl` gate lines; CI job conclusions in step-summary | `tail ci-report.jsonl`; GH Actions run page |
| Did the deployment succeed? | `post_deploy ok` + history entry + DeployFailed alert ABSENT | `grep -c failed deployments.jsonl`; `scripts/alerts.ps1` |
| Did it fail / roll back? | history `(rollback)` entries + `/deploys{failed}` posts + alert-api log | `grep rollback deployments.jsonl` |
| When did an incident occur? | alert-api `/alerts` timestamps + Prometheus alert `activeAt` | `scripts/alerts.ps1` |
| What recovery action occurred? | incident report timelines (INCIDENTS.md) + backup `.counts` + restore shell history | incident Evidence sections |

Supporting trails: `jobs`/`ehr_syncs` rows (per-attempt audit with cid),
`alertdata` volume (`alerts.jsonl`), CI artifacts (`release-evidence-<sha>`),
`ci-report.jsonl` (local gate history). Secrets NEVER appear in any trail:
readiness shows up/down only, logs truncate errors, `.env` is gitignored.
