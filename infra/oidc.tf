# Trust GitHub's OIDC issuer so Actions can assume a role with no stored AWS keys.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "ci_assume" {
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
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name               = "${var.prefix}-ci-deploy"
  assume_role_policy = data.aws_iam_policy_document.ci_assume.json
}

# Deploy permissions: PowerUserAccess (everything except IAM) + scoped IAM.
resource "aws_iam_role_policy_attachment" "ci_power" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

resource "aws_iam_role_policy" "ci_iam" {
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["iam:*"],
        Resource = "arn:aws:iam::${var.account_id}:role/${var.prefix}-*"
      },
      {
        Effect   = "Allow",
        Action   = ["iam:GetOpenIDConnectProvider", "iam:CreateOpenIDConnectProvider", "iam:TagOpenIDConnectProvider", "iam:UpdateOpenIDConnectProviderThumbprint", "iam:DeleteOpenIDConnectProvider"],
        Resource = "*"
      }
    ]
  })
}
