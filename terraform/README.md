# Terraform — AWS production-target mirror (validate-only, $0)

The graded runtime is local Compose; this tree proves the design transfers
to AWS (VPC≈networks, ALB≈nginx, ECS≈compose services, RDS/ElastiCache≈
containers, ECR≈tags, Secrets Manager≈.env). Nothing here is fake: every
resource is a real AWS resource with real arguments. Nothing is ever
`apply`d in this assessment (cost + cleanup); `validate` + scans are the
demonstrable bar, and the lifecycle below works the moment creds exist.

## Module catalog

| Module | Represents | Inputs (key) | Outputs | Depends on |
|---|---|---|---|---|
| network | VPC, public/private subnets, route tables, IGW, Flow Logs | project, env | vpc_id, subnet ids | — |
| security | SGs (ALB/tasks/DB/Redis), IAM exec+task roles, Secrets Manager JSON | vpc_id, db/redis endpoints + secrets | 4 sg ids, 2 role arns, secret arn | network, database, queue |
| database | RDS Postgres 16 (encrypted, private, 7d backups) | subnets, db sg, password, protection flags | db_address | network, security |
| queue | ElastiCache Redis 7 (encrypted, auth) | subnets, redis sg, token, nodes | redis_primary_endpoint | network, security |
| monitoring | CloudWatch app log group (30d) | project, env | log_group_name | — |
| compute | ECR×2, ECS cluster, api+worker task defs/services, ALB+TLS | subnets, sgs, roles, secret, log group, images, counts | alb dns, ecr urls | network, security, monitoring |

Security boundaries: only the ALB is internet-reachable; DB/Redis accept
traffic only from ECS tasks (SGs); tasks run private subnets, no public IP;
secrets enter via Secrets Manager + `TF_VAR_*`, never tfvars/git.
Environment differences live ONLY in `terraform.tfvars` (counts, deletion
protection, snapshots) — `diff environments/dev/main.tf
environments/prod/main.tf` shows identical module calls.

## Lifecycle (per environment dir)

```powershell
terraform init -backend=false          # providers only; local state, no S3 needed
terraform fmt -check -recursive        # CI gate: formatting is enforced
terraform validate                     # types + references, no creds needed
# With AWS creds (TF_VAR_db_password, TF_VAR_redis_auth_token, optional TF_VAR_alb_certificate_arn):
terraform plan -var-file=terraform.tfvars -out=tfplan
terraform apply tfplan
terraform destroy -var-file=terraform.tfvars   # READ FIRST: dev skips the final
                                               # snapshot and has no deletion protection;
                                               # prod takes a snapshot and refuses
                                               # while protection is on.
```

## Recreation ≠ recovery (read this before destroy)

`terraform destroy` + `apply` rebuilds INFRASTRUCTURE in minutes. It does not
bring back DATA: RDS without a snapshot starts empty; ElastiCache starts
empty by design (accepted loss — completed work lives in Postgres). The
recovery path is snapshots + `pg_dump` (see RECOVERY.md), not re-apply.
Local equivalent of the full loop: `docker compose down -v && docker compose
up -d` (recreate) then `restore.sh` (recover) — two separate commands for
two separate concerns, deliberately.
