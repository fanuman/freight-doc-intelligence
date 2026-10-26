# The Postgres database (RDS). Private: no public address, and only the app task's firewall group may connect.

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "main" {
  identifier        = var.name
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "freight_intel"
  username = "freight_intel_owner" # the OWNER: creates tables. The API logs in as a different, weaker role.

  # RDS creates the password, keeps it in Secrets Manager and can rotate it. We never choose or see it.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  # Demo settings, so that `terraform destroy` is quick and leaves nothing behind. A real system would
  # keep backups, take a final snapshot and turn on deletion protection.
  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
}
