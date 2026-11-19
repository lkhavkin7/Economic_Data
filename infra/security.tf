# Security groups: the firewall rules around the Lambda and the database.
# A security group is stateful: if a connection is allowed out, the reply is allowed
# back in automatically, so only the direction that opens the connection needs a rule.
# Everything here is free.

# Every VPC comes with a default security group that allows all traffic between its
# members. Declaring it with no rules makes Terraform remove those rules, so nothing
# can use it by accident.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project}-default-locked" }
}

# The Lambda function. It has no inbound rules: nothing opens connections to it.
resource "aws_security_group" "lambda" {
  name        = "${var.project}-lambda"
  description = "Lambda function: outbound only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-lambda" }
}

# The database. Its only inbound rule is below: PostgreSQL traffic from the Lambda.
resource "aws_security_group" "database" {
  name        = "${var.project}-database"
  description = "RDS PostgreSQL: reachable only from the Lambda"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-database" }
}

# The rules are separate resources, not blocks inside the groups above. Each group's
# rule points at the other group, and blocks inside both would make them wait on each
# other forever.

resource "aws_vpc_security_group_ingress_rule" "database_from_lambda" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.lambda.id # "anything wearing the Lambda group", not an IP range
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL from the Lambda"
}

resource "aws_vpc_security_group_egress_rule" "lambda_to_database" {
  security_group_id            = aws_security_group.lambda.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL to the database"
}

# FRED and Secrets Manager are both reached over HTTPS, through the NAT gateway.
resource "aws_vpc_security_group_egress_rule" "lambda_https" {
  security_group_id = aws_security_group.lambda.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS to the internet"
}