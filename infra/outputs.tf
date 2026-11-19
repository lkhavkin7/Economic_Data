# Values printed after "terraform apply", and readable later with "terraform output".

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "db_address" {
  value = aws_db_instance.main.address
}

# The ARN (the secret's full name) only. The password itself is not shown.
output "db_secret_arn" {
  value = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "lambda_function_name" {
  value = aws_lambda_function.main.function_name
}