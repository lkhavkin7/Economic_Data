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