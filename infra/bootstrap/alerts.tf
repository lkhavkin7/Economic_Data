# Where the alarms of the main stack send their messages. It lives here, not in the main stack,
# because the email subscription must be confirmed by hand, and a subscription inside the main
# stack would need confirming again after every destroy and apply.

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

# Sends every message on the topic to the email address. AWS emails a confirmation link
# first, and nothing is delivered until that link is clicked.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}