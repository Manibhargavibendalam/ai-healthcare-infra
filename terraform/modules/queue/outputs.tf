output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}
