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

variable "github_repo" {
  description = "The GitHub repository allowed to deploy, as owner/name."
  type        = string
  default     = "lkhavkin7/Economic_Data"
}

variable "github_branches" {
  description = "The branches of that repository allowed to deploy."
  type        = list(string)
  default     = ["main", "rewrite"]
}

# Has no default, so the address is never written in a file in the repository. Set it in the
# terminal before running terraform: set TF_VAR_alert_email=<your address>
variable "alert_email" {
  description = "Where the alarm emails go."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must look like an email address, such as name@example.com."
  }
}
