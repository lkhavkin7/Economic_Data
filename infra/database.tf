# The database: one small RDS PostgreSQL server in the private subnets.
# It costs about $0.016 per hour, plus a little for its 20 GB of storage.

# The subnets RDS may place the server in. It requires subnets in at least two
# availability zones, which is why network.tf made two private ones.
resource "aws_db_subnet_group" "main" {
  name       = var.project
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = var.project }
}

resource "aws_db_instance" "main" {
  identifier = var.project

  engine         = "postgres"
  engine_version = "16" # a major version only: AWS picks the newest minor release and applies later ones itself
  instance_class = "db.t4g.micro"

  allocated_storage = 20 # GB, the smallest size gp3 storage allows
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "econ_data" # created with the server; the schema is applied later by the Lambda's setup mode
  username = "econ"

  # RDS generates the master password itself and stores it in a Secrets Manager secret
  # it owns. The password is never written in these files or in the Terraform state.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1 # days of automated backups

  # Lets "terraform destroy" remove the server in one step, with no final backup
  # and no protection switch to turn off first. These are choices for a project that
  # is rebuilt from code and holds only data FRED can serve again.
  skip_final_snapshot = true
  deletion_protection = false
  apply_immediately   = true

  tags = { Name = var.project }
}