# The Lambda function that runs the pipeline. Lambda bills per run, so an idle
# function costs nothing.

# The function's logs. Created here, instead of letting Lambda create it on the first
# run, so that "terraform destroy" removes it too.
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project}"
  retention_in_days = 14
}

resource "aws_lambda_function" "main" {
  function_name = var.project
  role          = aws_iam_role.lambda.arn

  runtime       = "python3.13" # must match PYTHON_VERSION in scripts/build_lambda.py
  architectures = ["x86_64"]   # must match PLATFORM in scripts/build_lambda.py
  handler       = "src.econ_data.lambda_handler.lambda_handler"

  # The zip made by scripts/build_lambda.py. The hash is how Terraform notices the
  # code changed and uploads a new version.
  filename         = "${path.module}/../build/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/lambda.zip")

  timeout     = 300 # seconds
  memory_size = 256 # MB

  # Writes every log line as JSON, so CloudWatch can search and count by field. Anything the
  # code passes as logging's "extra" becomes a field of its own.
  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO" # the lowest level of the code's own log lines that is kept
    log_group             = aws_cloudwatch_log_group.lambda.name
  }

  # Runs the function inside the private subnets, wearing the Lambda security group.
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  # The settings the code reads with Settings(). There is no DB_PASSWORD: the code
  # finds the password itself, using DB_SECRET_ARN.
  environment {
    variables = {
      DB_HOST       = aws_db_instance.main.address
      DB_PORT       = "5432"
      DB_NAME       = "econ_data"
      DB_USER       = "econ"
      DB_SECRET_ARN = aws_db_instance.main.master_user_secret[0].secret_arn
      FRED_API_KEY  = var.fred_api_key
    }
  }

  # Things the function needs in place before it can run, which none of the settings
  # above refer to: its permissions, its log group, and its route to the internet.
  depends_on = [
    aws_iam_role_policy_attachment.lambda_vpc_and_logs,
    aws_iam_role_policy.read_database_secret,
    aws_cloudwatch_log_group.lambda,
    aws_route.private_internet,
  ]
}