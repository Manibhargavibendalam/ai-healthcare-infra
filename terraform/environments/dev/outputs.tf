output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "ecr_api_url" {
  value = module.compute.ecr_api_url
}

output "ecr_worker_url" {
  value = module.compute.ecr_worker_url
}

output "rds_address" {
  value = module.database.db_address
}

output "redis_primary_endpoint" {
  value = module.queue.redis_primary_endpoint
}
