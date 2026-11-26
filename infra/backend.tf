# Keeps the state of this configuration in the S3 bucket made by infra/bootstrap, so that
# both your laptop and GitHub Actions work from the same state.
# The bucket name is left out on purpose: it is passed when running "terraform init":
#   terraform init -backend-config="bucket=<the state_bucket output of infra/bootstrap>"
terraform {
  backend "s3" {
    key          = "econ-data/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true # a lock file in the bucket stops two runs from changing the state at once
  }
}