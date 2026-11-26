# The two values GitHub needs, entered once as repository variables.

output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

# For testing the topic from the terminal. The main stack finds the topic by its name.
output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}