variable "project" {
  type    = string
  default = "ai-healthcare-infra"
}

variable "env" {
  type    = string
  default = "prod-like"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "api_count" {
  type    = number
  default = 2
}

variable "worker_count" {
  type    = number
  default = 2
}

variable "redis_nodes" {
  type    = number
  default = 2
}

variable "db_deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}

variable "api_image" {
  type    = string
  default = "api:prod-like"
}

variable "worker_image" {
  type    = string
  default = "worker:prod-like"
}

# ACM cert for the :443 listener. Empty keeps validate credential-free;
# a real deploy passes TF_VAR_alb_certificate_arn (see COST.md TLS note).
variable "alb_certificate_arn" {
  type    = string
  default = ""
}

# No defaults: TF_VAR_db_password / TF_VAR_redis_auth_token. Never in files.
variable "db_password" {
  type      = string
  sensitive = true
}

variable "redis_auth_token" {
  type      = string
  sensitive = true
}
