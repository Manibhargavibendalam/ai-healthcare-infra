# Compute = ECS Fargate (no Kubernetes by design, see DECISIONS.md).
# ALB is the controlled ingress (mirrors NGINX locally). api is the only
# service behind the ALB; worker runs as a private service.
# Identity (roles), secrets, and log sink arrive as INPUTS from the
# security/monitoring modules — compute owns neither credentials nor logs.
# TLS: :80 redirects to :443; :443 terminates with an ACM cert supplied as
# alb_certificate_arn (empty default keeps validate credential-free; a real
# deploy passes TF_VAR_alb_certificate_arn).
resource "aws_ecr_repository" "api" {
  name                 = "${var.project}/api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${var.project}/worker"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.env}"
}

# trivy:ignore:AVD-AWS-0053: this ALB IS the public ingress by design (mirrors local nginx :8080)
resource "aws_lb" "main" {
  name                       = "${var.project}-${var.env}"
  load_balancer_type         = "application"
  drop_invalid_header_fields = true
  subnets                    = var.public_subnet_ids
  security_groups            = [var.alb_sg_id]
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api-${var.env}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.alb_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api-${var.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.exec_role_arn
  task_role_arn            = var.task_role_arn
  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    essential    = true
    portMappings = [{ containerPort = 8000 }]
    environment  = [{ name = "API_VERSION", value = var.env }]
    secrets = [
      { name = "DATABASE_URL", valueFrom = "${var.app_secret_arn}:DATABASE_URL::" },
      { name = "REDIS_URL", valueFrom = "${var.app_secret_arn}:REDIS_URL::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = var.log_group_name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api-${var.env}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker-${var.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.exec_role_arn
  task_role_arn            = var.task_role_arn
  container_definitions = jsonencode([{
    name      = "worker"
    image     = var.worker_image
    essential = true
    environment = [
      { name = "EHR_URL", value = "http://ehr.local:8002" },
      { name = "AI_URL", value = "http://ai.local:8001" },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = "${var.app_secret_arn}:DATABASE_URL::" },
      { name = "REDIS_URL", valueFrom = "${var.app_secret_arn}:REDIS_URL::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = var.log_group_name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker-${var.env}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }
}
