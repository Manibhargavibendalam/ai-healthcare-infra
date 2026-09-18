variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "redis_sg_id" {
  type = string
}

variable "redis_auth_token" {
  type      = string
  sensitive = true
}

variable "redis_nodes" {
  type = number
}
