data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---- Query Lambda role: read index, read chunks, read SSM, write logs ----
resource "aws_iam_role" "query" {
  name               = "${var.prefix}-query-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "query" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.index.arn}/*"]
  }
  statement {
    actions   = ["dynamodb:BatchGetItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.chunks.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [data.aws_ssm_parameter.groq_key.arn, data.aws_ssm_parameter.gemini_key.arn]
  }
}

resource "aws_iam_role_policy" "query" {
  role   = aws_iam_role.query.id
  policy = data.aws_iam_policy_document.query.json
}

resource "aws_iam_role_policy_attachment" "query_logs" {
  role       = aws_iam_role.query.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ---- Ingest Lambda role: write index + write/read chunks + read SSM + logs ----
resource "aws_iam_role" "ingest" {
  name               = "${var.prefix}-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ingest" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.index.arn}/*"]
  }
  statement {
    actions   = ["dynamodb:BatchWriteItem", "dynamodb:PutItem", "dynamodb:BatchGetItem"]
    resources = [aws_dynamodb_table.chunks.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [data.aws_ssm_parameter.groq_key.arn, data.aws_ssm_parameter.gemini_key.arn]
  }
}

resource "aws_iam_role_policy" "ingest" {
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_iam_role_policy_attachment" "ingest_logs" {
  role       = aws_iam_role.ingest.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
