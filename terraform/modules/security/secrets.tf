# One Secrets Manager secret holds both connection strings as JSON.
# Tasks receive them as env vars at launch; values live only in
# Secrets Manager + TF_VAR_* inputs, never in code, images, tfvars, or git.
resource "aws_secretsmanager_secret" "app" {
  name = "${var.project}/app/${var.env}"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL = "postgresql://app:${var.db_password}@${var.db_address}:5432/healthcare"
    REDIS_URL    = "rediss://:${var.redis_auth_token}@${var.redis_primary_endpoint}:6379/0"
  })
}
