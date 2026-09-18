# Private Redis for the job queue. Encrypted in transit + at rest,
# auth token required. Mirrors local redis with --requirepass.
# Ephemeral by design: queued-but-unprocessed jobs do NOT survive a
# destroy (accepted loss, see RECOVERY.md); completed work lives in Postgres.
resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-${var.env}"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = "${var.project}-${var.env}"
  description                = "job queue redis"
  engine                     = "redis"
  engine_version             = "7.0"
  node_type                  = "cache.t3.micro"
  num_cache_clusters         = var.redis_nodes
  parameter_group_name       = "default.redis7"
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [var.redis_sg_id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.redis_auth_token
  automatic_failover_enabled = var.redis_nodes > 1
}
