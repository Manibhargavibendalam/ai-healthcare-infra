variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "db_sg_id" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "db_deletion_protection" {
  type = bool
}

variable "skip_final_snapshot" {
  type = bool
}
