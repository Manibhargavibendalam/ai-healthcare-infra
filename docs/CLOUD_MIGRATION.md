# CLOUD MIGRATION

Local → AWS with minimal conceptual redesign (validate-only TF mirror in
`../terraform/` proves each mapping; no real deployment per PDF RULE 5).

| Local | Cloud | Notes |
|---|---|---|
| Nginx :8080 | ALB + ACM TLS (:80→:443, TLS13) | TF ready; needs cert ARN |
| API containers | ECS Fargate (api_count) / EC2 | task defs mirror compose services |
| Worker containers | independent Fargate (worker_count) | HPA on queue age in prod |
| Redis container | ElastiCache Redis (auth + TLS) | TF `queue` module |
| PostgreSQL container | RDS Postgres (Multi-AZ, snapshots) | TF `database` module |
| Terraform validate-only | same TF applied (plan → apply) | needs creds; watch NAT + snapshot costs |
| GitHub Actions + ci.sh | Actions with OIDC deploy role | same 13 stages |
| Prometheus/Grafana local | self-hosted or AMP + AMG | retention/cardinality bills |
| `.env` file | Secrets Manager + CI secrets | TF `security` module already wires it |
| Task container users | IAM execution/task roles | least-privilege split already modeled |
| edge/internal networks | VPC + public/private subnets + SGs | TF `network`+`security` modules |
| pg_dump files | RDS snapshots + S3 versioning | tested restores, PITR |

What changes operationally: TLS everywhere, HPA instead of hand scaling,
automated backups instead of manual dumps, remote-write retention policy,
NAT-or-VPC-endpoints for pulls, WAF optional. What does NOT change:
service boundaries, queue protocol, retry policy, deploy gates, alert
contracts, log schema. Cost lens: `../COST.md`.
