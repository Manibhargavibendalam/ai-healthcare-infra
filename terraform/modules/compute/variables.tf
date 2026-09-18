variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "alb_sg_id" {
  type = string
}

variable "ecs_sg_id" {
  type = string
}

variable "exec_role_arn" {
  type        = string
  description = "From the security module: least-privilege task identity"
}

variable "task_role_arn" {
  type        = string
  description = "From the security module: zero extra permissions"
}

variable "app_secret_arn" {
  type        = string
  description = "From the security module: Secrets Manager JSON with connection strings"
}

variable "log_group_name" {
  type        = string
  description = "From the monitoring module: central CloudWatch sink"
}

variable "alb_certificate_arn" {
  type        = string
  description = "ACM cert for the :443 listener; empty keeps validate credential-free"
  default     = ""
}

variable "api_count" {
  type = number
}

variable "worker_count" {
  type = number
}

variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
}
