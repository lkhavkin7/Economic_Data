# The inputs of this configuration. Every one has a default, so none must be set.

variable "region" {
  description = "AWS region to build in."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name used to tag and name every resource."
  type        = string
  default     = "econ-data"
}

variable "vpc_cidr" {
  description = "Address range of the VPC. The subnets are carved out of it."
  type        = string
  default     = "10.20.0.0/16"
}

# Has no default, so it is never written in a file. Set it in the terminal before running
# terraform: set TF_VAR_fred_api_key=<the key>
variable "fred_api_key" {
  description = "FRED API key, given to the Lambda as an environment variable."
  type        = string
  sensitive   = true # hidden in plan and apply output
}

variable "schedule" {
  description = "When the daily run happens, as an EventBridge cron expression (in UTC)."
  type        = string
  default     = "cron(0 13 * * ? *)" # every day at 13:00 UTC, which is 8 or 9 in the morning in Boston
}