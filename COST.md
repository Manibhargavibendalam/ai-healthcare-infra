# COST & TRADE-OFFS (M13)

Posture: **$0 for the whole assessment.** Local Docker is free; the Terraform
mirror is validate-only and never applied. Everything below analyzes the
architecture AS IF deployed, so a production engineer can see what it costs
to operate — not just whether it works.

## 1. Cost model if applied (rough monthly, ap-south-1)

| Resource | Dev | Prod-like | Scales with |
|---|---|---|---|
| ECS Fargate 0.25vCPU/0.5GB | ~$9 × tasks | ×4 tasks | api/worker counts (independent) |
| RDS db.t3.micro 20GB + 7d backup | ~$15 | same class | storage, retention, Multi-AZ option |
| ElastiCache t3.micro ×1/×2 | ~$13 | ~$26 | nodes, failover |
| ALB + LCU | ~$17 + use | same | traffic |
| NAT (if added for ECR pulls) | $0 (omitted) | ~$32+ | data processed |
| CloudWatch logs (30d) + metrics | ~$2–5 | ~$5–10 | log volume, retention, custom metrics |
| ECR storage | <$1 | <$1 | image count × size |
| S3 backups/snapshots | ~$1 | ~$3–5 | retention, frequency |
| Secrets Manager | <$1 | <$1 | secret count, API calls |

## 2. Resource classification

- Scale dynamically: api tasks (request rate), worker tasks (queue depth/age),
  ALB capacity (traffic). These are the ONLY knobs tied to load.
- Remain minimal: Redis (job pointers, tiny), ECR (few MB images), Secrets
  Manager (2 secrets), Flow Logs (sampled if noisy).
- Expensive watchlist: RDS (always-on baseline + storage growth + Multi-AZ
  doubles it), Fargate idle tasks (pay per second even at 3am), NAT if added,
  CloudWatch (log volume is the silent killer — JSON lines at high request
  rates × 30d retention).
- Overprovisioning risks: api_count=2/worker_count=2 in prod-like before
  traffic justifies it; `db.t3.micro` → larger class "just in case"; 7-day
  RDS backups + snapshots + pg_dumps kept forever; Prometheus 15s scrape
  interval on dozens of targets (local: fine; cloud: remote-write bills).
- Network/egress: intra-VPC traffic free; ALB→internet egress and any
  cross-region replication bill per GB. No NAT today = no per-GB tax, but
  also no outbound path (documented prod hardening: NAT or VPC endpoints).

## 3. Every major technology: why, problem, alternatives, trade-off

| Tech | Why chosen | Problem solved | Alternatives | Trade-off introduced |
|---|---|---|---|---|
| Docker | reproducible runtime, same image dev→prod | "works on my machine" | VMs, bare metal, nix | daemon overhead, image CVE surface |
| Nginx | single controlled door + DNS-based balancing | ingress, blue/green without orchestrator | ALB-only, Traefik, Caddy | static config, 5s DNS TTL coarseness |
| Redis | list ops = depth, blocking pop, atomic move | queue with observability built-in | SQS, Kafka, RabbitMQ | ephemeral; single instance; no groups |
| PostgreSQL | relational state + audit tables + pg_dump story | durable app + operational state | MySQL, SQLite, DynamoDB | single stateful SPOF; needs backup discipline |
| Terraform | versioned, reviewable, destroyable infra | reproducible cloud, env parity | ClickOps, CloudFormation, Pulumi | HCL learning curve; state management burden |
| GitHub Actions | pipeline colocated with code, free minutes | automated gates + audit trail | Jenkins, GitLab CI, local-only ci.sh | runner minutes, ephemeral state (release job) |
| Prometheus | pull metrics, PromQL, alert rules as code | detection + dashboards + paging from one source | Datadog, CloudWatch, InfluxDB | self-hosted storage/retention ops |
| Grafana | provisioned dashboards, threshold tiles | one screen answering 11 questions | Kibana, CloudWatch dashboards | another stateful service to run |
| Trivy | one tool: fs deps + misconfig + images | vuln + IaC policy with zero new infra | Snyk, Grype, Scout | DB freshness; image scans need daemon |
| Gitleaks | fast secret regexes, git-aware | leaked-credential gate in seconds | trufflehog, git-secrets | allowlist foot-guns (see D32) |
| Checkov | 1000+ TF policy checks | IaC misconfig gate | tfsec, OPA/Conftest | heavy deps; host-blocked here (CI-only) |
| Python/FastAPI | tiny services, TestClient, /metrics ecosystem | mock workloads + health + metrics fast | Go, Node, Java | GIL throughput; slower than Go per core |

No entry claims universal superiority — each row names what was GIVEN UP.

## 4. Five-way tensions (concrete, from this repo)

- Reliability vs cost: 2 replicas + Multi-AZ RDS survive AZ loss; we run 1
  of each locally and accept restart-level recovery. The SPOF table (RECOVERY.md)
  prices every "just add redundancy" instinct.
- Performance vs simplicity: a connection pooler (PgBouncer) would raise API
  throughput; one `psycopg2.connect` per request keeps the code explainable.
  Chosen: simplicity, with the ceiling documented (SCALING.md bottleneck #2).
- Security vs simplicity: read-only filesystems + dropped caps on 11 services
  cost us tmpfs reasoning and a live-verify step; worth it for blast-radius
  reduction. Secrets Manager over env files costs IAM complexity; kept local
  simple, cloud correct.
- Reliability vs simplicity: blue/green via nginx+scripts instead of an
  orchestrator — fewer moving parts, but the operator (not a controller)
  owns the switch. Stated, not hidden.
- Cost vs everything: validate-only Terraform, no NAT, single-AZ-lean sizes,
  30d log retention — each is a deliberate under-spend with a named prod
  upgrade path, never an accidental gap.

## 5. Local simulation → real cloud: what changes

| Local | Cloud | Why it changes |
|---|---|---|
| compose networks | VPC + SGs (already mirrored in TF) | real L3 isolation + auditing |
| nginx :8080 | ALB + ACM TLS (TF ready, needs cert ARN) | public internet needs TLS + L7 |
| `--scale` by hand | HPA on latency/queue-age | humans don't scale at 3am |
| .env file | Secrets Manager + CI secrets (TF ready) | rotation, audit, no disk secrets |
| pg_dump cron? manual | RDS automated backups + snapshots | tested restores, PITR |
| Prometheus local disk | remote-write / AMP + retention policy | disk + cardinality bills |
| `ci.sh` gates | identical gates in Actions (already mirrored) | shared runners, required checks |
| single host | multi-AZ, NAT/VPC endpoints, WAF (optional) | fault isolation; each adds $ |

Free-tier note: new accounts cover 750 hrs/mo t3.micro RDS + EC2 for 12
months — a dev apply *could* fit, but validate-only removes all billing risk
and cleanup duty.
