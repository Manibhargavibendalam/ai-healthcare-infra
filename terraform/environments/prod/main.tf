# prod-like environment: identical module calls as dev.
# Only the tfvars differ (counts, protection). This is the "reuse the same
# infrastructure structure" requirement made literal.
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      ManagedBy = "terraform"
    }
  }
}

module "network" {
  source  = "../../modules/network"
  project = var.project
  env     = var.env
}

module "database" {
  source                 = "../../modules/database"
  project                = var.project
  env                    = var.env
  private_subnet_ids     = module.network.private_subnet_ids
  db_sg_id               = module.security.db_sg_id
  db_password            = var.db_password
  db_deletion_protection = var.db_deletion_protection
  skip_final_snapshot    = var.skip_final_snapshot
}

module "queue" {
  source             = "../../modules/queue"
  project            = var.project
  env                = var.env
  private_subnet_ids = module.network.private_subnet_ids
  redis_sg_id        = module.security.redis_sg_id
  redis_auth_token   = var.redis_auth_token
  redis_nodes        = var.redis_nodes
}

module "security" {
  source                 = "../../modules/security"
  project                = var.project
  env                    = var.env
  vpc_id                 = module.network.vpc_id
  db_address             = module.database.db_address
  redis_primary_endpoint = module.queue.redis_primary_endpoint
  db_password            = var.db_password
  redis_auth_token       = var.redis_auth_token
}

module "monitoring" {
  source  = "../../modules/monitoring"
  project = var.project
  env     = var.env
}

module "compute" {
  source              = "../../modules/compute"
  project             = var.project
  env                 = var.env
  region              = var.region
  vpc_id              = module.network.vpc_id
  public_subnet_ids   = module.network.public_subnet_ids
  private_subnet_ids  = module.network.private_subnet_ids
  alb_sg_id           = module.security.alb_sg_id
  ecs_sg_id           = module.security.ecs_sg_id
  exec_role_arn       = module.security.exec_role_arn
  task_role_arn       = module.security.task_role_arn
  app_secret_arn      = module.security.app_secret_arn
  log_group_name      = module.monitoring.log_group_name
  alb_certificate_arn = var.alb_certificate_arn
  api_count           = var.api_count
  worker_count        = var.worker_count
  api_image           = var.api_image
  worker_image        = var.worker_image
}
