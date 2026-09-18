variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "db_address" {
  type        = string
  description = "RDS endpoint, interpolated into the secret (never stored in tfvars)"
  default     = "db.local"
}

variable "redis_primary_endpoint" {
  type        = string
  description = "ElastiCache endpoint, interpolated into the secret (never stored in tfvars)"
  default     = "redis.local"
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = null
}

variable "redis_auth_token" {
  type      = string
  sensitive = true
  default   = null
}
