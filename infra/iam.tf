# The Lambda's identity: an IAM role, and the permissions attached to it.
# IAM is free.

# Who may use the role. This "trust policy" lets the Lambda service, and nothing else, take it on.
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.project}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

# AWS's own policy for a Lambda inside a VPC. It allows creating and removing the network
# interfaces that connect the function to the subnets, and writing its logs.
resource "aws_iam_role_policy_attachment" "lambda_vpc_and_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# The one extra permission: reading the database password secret, and no other secret.
data "aws_iam_policy_document" "read_database_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "read_database_secret" {
  name   = "read-database-secret"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.read_database_secret.json
}