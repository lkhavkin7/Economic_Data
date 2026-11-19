# The daily trigger: an EventBridge rule that invokes the Lambda in fetch mode.
# EventBridge rules and Lambda invocations from them cost next to nothing.

resource "aws_cloudwatch_event_rule" "daily" {
  name                = "${var.project}-daily"
  description         = "Runs the econ-data pipeline once a day."
  schedule_expression = var.schedule
}

# What the rule does when it fires: call the Lambda, with this event as its input.
resource "aws_cloudwatch_event_target" "daily" {
  rule = aws_cloudwatch_event_rule.daily.name
  arn  = aws_lambda_function.main.arn

  input = jsonencode({ mode = "fetch" })
}

# Lambda refuses calls from other AWS services unless it is told they are allowed.
# This lets EventBridge, and only this one rule, invoke the function.
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeDaily"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily.arn
}