# Least-privilege security groups. Only the ALB is reachable from the
# internet; DB/Redis accept traffic ONLY from ECS tasks. This mirrors
# the Compose rule "no ports published for db/redis/worker/ai/ehr".
# Egress is restricted (no 0.0.0.0/0 allow-all): tasks need only HTTPS
# (ECR, Secrets Manager, AWS APIs) + DNS; the ALB needs only the app ports.
# NOTE: the ALB->tasks egress lives in a standalone rule resource below.
# Inlining it in the ALB block would create an SG reference cycle
# (alb<->ecs); separate rule resources break the cycle properly.
resource "aws_security_group" "alb" {
  name        = "${var.project}-alb-${var.env}"
  description = "Public ingress: HTTP only"
  vpc_id      = var.vpc_id

  ingress {
    description = "http from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group_rule" "alb_to_ecs" {
  type                     = "egress"
  from_port                = 8000
  to_port                  = 8002
  protocol                 = "tcp"
  security_group_id        = aws_security_group.alb.id
  source_security_group_id = aws_security_group.ecs.id
  description              = "app ports to tasks only"
}

resource "aws_security_group" "ecs" {
  name        = "${var.project}-ecs-${var.env}"
  description = "Tasks: app ports from ALB only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "app from ALB"
    from_port       = 8000
    to_port         = 8002
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # tfsec:ignore:aws-vpc-no-public-egress-sgr: tasks need HTTPS (ECR/secrets/APIs) + DNS with no NAT/VPC endpoints; least ports, documented in COST.md
  egress {
    description = "https to AWS APIs/ECR/secrets"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # tfsec:ignore:aws-vpc-no-public-egress-sgr: DNS is required for service discovery; no resolver inside the VPC without extra infra
  egress {
    description = "dns udp"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # tfsec:ignore:aws-vpc-no-public-egress-sgr: see dns udp above
  egress {
    description = "dns tcp"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name        = "${var.project}-db-${var.env}"
  description = "Postgres: tasks only, never the internet"
  vpc_id      = var.vpc_id

  ingress {
    description     = "postgres from tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  # No egress block: SGs are stateful, return traffic is automatic, and the
  # DB initiates no outbound connections. (Omitting egress keeps the AWS
  # default, which only ever carries established replies here.)
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-redis-${var.env}"
  description = "Redis: tasks only, never the internet"
  vpc_id      = var.vpc_id

  ingress {
    description     = "redis from tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
  # Same as db: stateful replies only, no initiated outbound.
}
