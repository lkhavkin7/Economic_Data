# Credentials come from the AWS CLI, as in the main configuration:
# run "set AWS_PROFILE=econ" in the terminal first.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform-bootstrap"
    }
  }
}