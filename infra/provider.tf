# The AWS provider: which region to work in, and the tags added to everything created.
# Credentials are not set here. The provider finds them the way the AWS CLI does,
# so run "set AWS_PROFILE=econ" in the terminal before running terraform.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}