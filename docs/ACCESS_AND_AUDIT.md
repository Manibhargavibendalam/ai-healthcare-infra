# ACCESS AND AUDIT

## Five access levels (least privilege)

| Role | Gets | Denied | Enforced by |
|---|---|---|---|
| Developer | repo, drills, ci.sh, logs/metrics read | `.env` values, prod creds | gitignore, no shared secrets |
| Deployment (CI + deploy.sh) | build, gates, recreate api, post /deploys | host access, DB writes, secret values | ci.yml needs, scripts |
| Infra admin | terraform plan/apply/destroy, TF_VAR_* | app data, routine deploys | separate TF workflow |
| Runtime (api/worker) | internal-net deps only, no inbound for worker | internet, host, each other's scope | networks, SGs, non-root |
| Monitoring | scrape/read logs, receive webhooks | writes, deploys, secret values | overlay, read-only mounts |

Cloud mapping: developer→IAM users + MFA; deployment→OIDC role for Actions
(short-lived, deploy-only); infra admin→break-glass admin role + CloudTrail;
runtime→ECS task/execution roles (already in `terraform/modules/security`);
monitoring→read-only + CloudWatch read. Full matrix: `../SECURITY.md`.

## Auditability (7 questions → evidence)

Who deployed (`actor` in `deployments.jsonl`) · what version (`/health`,
`api_build_info`, history) · infra changes (`git log`, TF plan) · security
checks (`ci-report.jsonl`, Actions conclusions) · success/failure (history +
DeployFailed absence/presence) · incident time (alert-api timestamps) ·
recovery action (INCIDENTS.md timelines + backup `.counts`). Full matrix with
commands: `../AUDITABILITY.md`. Secrets never appear in any trail.
