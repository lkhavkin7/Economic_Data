# Lets GitHub Actions workflows from one repository sign in to AWS without any stored password.
# GitHub vouches for each workflow run with a signed token (OpenID Connect), and AWS accepts
# the token only when it matches the rules in the role's trust policy below.

# Tells AWS to accept tokens issued by GitHub. There can be only one of these per account.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# Who may take on the deploy role: only workflow runs of this repository, on these branches.
data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for branch in var.github_branches : "repo:${var.github_repo}:ref:refs/heads/${branch}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${var.project}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600 # seconds: the temporary credentials last one hour
}

# Everything Terraform builds, apart from IAM: network, database, Lambda, EventBridge, logs, S3.
resource "aws_iam_role_policy_attachment" "power_user" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# PowerUserAccess excludes IAM, but the main configuration creates the Lambda's role.
# This allows managing roles whose names start with the project name, and no others.
data "aws_iam_policy_document" "manage_project_roles" {
  statement {
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:PassRole",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project}-*"]
  }
}

resource "aws_iam_role_policy" "manage_project_roles" {
  name   = "manage-project-roles"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.manage_project_roles.json
}