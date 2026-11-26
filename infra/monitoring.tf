# Alarms that email you when the pipeline breaks or goes quiet. CloudWatch alarms cost cents
# a month, and the first 10 are free.

# The topic made by infra/bootstrap, found by its name. It lives outside this stack, so it,
# and your confirmed email subscription, survive "terraform destroy".
data "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

# --- Alarm 1: a run failed ----------------------------------------------------------------
# Lambda counts an invocation as an error when the code raises. A fetch run in which any
# indicator failed raises on purpose, so this covers both a crash and a failed indicator.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name        = "${var.project}-lambda-errors"
  alarm_description = "The pipeline Lambda raised an error: an indicator failed, or the run crashed."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.main.function_name }

  statistic           = "Sum"
  period              = 300 # seconds: one 5-minute window
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  # No invocations means no data points, and that is fine here.
  treat_missing_data = "notBreaching"

  alarm_actions = [data.aws_sns_topic.alerts.arn]
  ok_actions    = [data.aws_sns_topic.alerts.arn]
}

# --- Alarm 2: no new data -----------------------------------------------------------------
# The code logs one JSON line per run with "event": "run_summary" and the number of rows it
# wrote. This filter turns each of those lines into a data point of a custom metric.
resource "aws_cloudwatch_log_metric_filter" "rows_written" {
  name           = "${var.project}-rows-written"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "{ $.event = \"run_summary\" }"

  metric_transformation {
    name      = "RowsWritten"
    namespace = "EconData"
    value     = "$.rows_written" # the field of the log line to record
    unit      = "Count"
  }
}

# Fires when four days in a row had no rows written. Four, not two, because on a weekend FRED
# publishes nothing new, so a run can legitimately write zero rows for two or three days.
# A day with no run at all has no data point, and is treated as a bad day as well, so this
# also catches a schedule that stopped firing.
resource "aws_cloudwatch_metric_alarm" "no_new_data" {
  alarm_name        = "${var.project}-no-new-data"
  alarm_description = "No new or changed rows in 4 days, or the daily run did not happen."

  namespace   = aws_cloudwatch_log_metric_filter.rows_written.metric_transformation[0].namespace
  metric_name = aws_cloudwatch_log_metric_filter.rows_written.metric_transformation[0].name

  statistic           = "Sum"
  period              = 86400 # seconds: one day
  evaluation_periods  = 4
  datapoints_to_alarm = 4
  threshold           = 0
  comparison_operator = "LessThanOrEqualToThreshold"

  treat_missing_data = "breaching"

  alarm_actions = [data.aws_sns_topic.alerts.arn]
  ok_actions    = [data.aws_sns_topic.alerts.arn]
}