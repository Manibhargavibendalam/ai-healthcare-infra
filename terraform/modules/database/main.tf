# Private Postgres. Encrypted, no public access, automated backups.
# Recovery story (RPO/RTO) is documented in RECOVERY.md; the local
# equivalent is pg_dump/restore. Destroying this module LOSES data unless
# a snapshot exists — recreation of infrastructure never implies recovery
# of state (see terraform/README.md).
resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-${var.env}"
  subnet_ids = var.private_subnet_ids
}

resource "aws_db_instance" "main" {
  identifier                          = "${var.project}-${var.env}"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = "db.t3.micro"
  allocated_storage                   = 20
  db_name                             = "healthcare"
  username                            = "app"
  password                            = var.db_password
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [var.db_sg_id]
  publicly_accessible                 = false
  storage_encrypted                   = true
  iam_database_authentication_enabled = true
  backup_retention_period             = 7
  # tfsec:ignore:aws-rds-enable-deletion-protection: dev teardown convenience; prod enforces true via tfvars
  deletion_protection = var.db_deletion_protection
  skip_final_snapshot = var.skip_final_snapshot
}
