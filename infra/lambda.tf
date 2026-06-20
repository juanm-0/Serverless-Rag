# Zip the build/ dir (populated by scripts/build_lambda.sh) into a deployable package.
data "archive_file" "package" {
  type        = "zip"
  source_dir  = "${path.module}/build"
  output_path = "${path.module}/build.zip"
}

locals {
  lambda_env = {
    INDEX_BUCKET = aws_s3_bucket.index.bucket
    CHUNKS_TABLE = aws_dynamodb_table.chunks.name
    LLM_PROVIDER = "groq"
  }
}

resource "aws_cloudwatch_log_group" "query" {
  name              = "/aws/lambda/${var.prefix}-query"
  retention_in_days = 30
}

resource "aws_lambda_function" "query" {
  function_name    = "${var.prefix}-query"
  role             = aws_iam_role.query.arn
  runtime          = "python3.12"
  handler          = "handlers.query_handler.handler"
  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256
  timeout          = 30
  memory_size      = 512
  environment {
    variables = local.lambda_env
  }
  depends_on = [aws_cloudwatch_log_group.query]
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.prefix}-ingest"
  retention_in_days = 30
}

resource "aws_lambda_function" "ingest" {
  function_name = "${var.prefix}-ingest"
  role          = aws_iam_role.ingest.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.ingest.repository_url}:${var.ingest_image_tag}"
  timeout       = 900 # 15 min for async ingest
  memory_size   = 1024
  ephemeral_storage {
    size = 2048 # /tmp for the git clone
  }
  environment {
    variables = local.lambda_env
  }
  depends_on = [aws_cloudwatch_log_group.ingest]
}
