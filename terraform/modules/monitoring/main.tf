# Central log sink for all task stdout (mirrors `docker compose logs`).
# Owned here — not in compute — so log retention is a monitoring decision,
# and compute only receives the group NAME as an input.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/${var.env}"
  retention_in_days = 30
}
