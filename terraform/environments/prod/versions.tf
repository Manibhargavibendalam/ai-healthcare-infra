terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # Local state only. Remote state (S3 + locking) is a documented
  # production hardening step, not needed for this mirror.
}
