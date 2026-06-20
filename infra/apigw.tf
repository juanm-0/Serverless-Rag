resource "aws_api_gateway_rest_api" "api" {
  name = "${var.prefix}-api"
}

# ---------- /query : synchronous Lambda proxy ----------
resource "aws_api_gateway_resource" "query" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "query"
}

resource "aws_api_gateway_method" "query_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.query.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "query" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.query.id
  http_method             = aws_api_gateway_method.query_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.query.invoke_arn
}

resource "aws_lambda_permission" "query" {
  statement_id  = "AllowAPIGatewayQuery"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

# ---------- /ingest : asynchronous (returns 202 immediately) ----------
resource "aws_api_gateway_resource" "ingest" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "ingest"
}

resource "aws_api_gateway_method" "ingest_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.ingest.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

# Role letting API Gateway invoke the ingest Lambda
data "aws_iam_policy_document" "apigw_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apigw_invoke" {
  name               = "${var.prefix}-apigw-invoke"
  assume_role_policy = data.aws_iam_policy_document.apigw_assume.json
}

resource "aws_iam_role_policy" "apigw_invoke" {
  role = aws_iam_role.apigw_invoke.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = "lambda:InvokeFunction",
      Resource = aws_lambda_function.ingest.arn
    }]
  })
}

# AWS service integration that invokes Lambda asynchronously via the Event type
resource "aws_api_gateway_integration" "ingest" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.ingest.id
  http_method             = aws_api_gateway_method.ingest_post.http_method
  integration_http_method = "POST"
  type                    = "AWS"
  uri                     = "arn:aws:apigateway:${var.region}:lambda:path/2015-03-31/functions/${aws_lambda_function.ingest.arn}/invocations"
  credentials             = aws_iam_role.apigw_invoke.arn
  request_parameters = {
    "integration.request.header.X-Amz-Invocation-Type" = "'Event'"
  }
}

resource "aws_api_gateway_method_response" "ingest_202" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.ingest.id
  http_method = aws_api_gateway_method.ingest_post.http_method
  status_code = "202"
}

resource "aws_api_gateway_integration_response" "ingest_202" {
  rest_api_id        = aws_api_gateway_rest_api.api.id
  resource_id        = aws_api_gateway_resource.ingest.id
  http_method        = aws_api_gateway_method.ingest_post.http_method
  status_code        = aws_api_gateway_method_response.ingest_202.status_code
  selection_pattern  = "" # default mapping (Lambda async returns an empty 202 body)
  response_templates = { "application/json" = jsonencode({ status = "accepted" }) }
  depends_on         = [aws_api_gateway_integration.ingest]
}

# ---------- deployment + stage ----------
resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.query.id,
      aws_api_gateway_resource.ingest.id,
      aws_api_gateway_method.query_post.id,
      aws_api_gateway_method.ingest_post.id,
      aws_api_gateway_integration.query.id,
      aws_api_gateway_integration.ingest.id,
      aws_api_gateway_integration_response.ingest_202.id,
    ]))
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.api.id
  stage_name    = "prod"
}

# ---------- usage plan + API key (abuse control) ----------
resource "aws_api_gateway_api_key" "key" {
  name = "${var.prefix}-key"
}

resource "aws_api_gateway_usage_plan" "plan" {
  name = "${var.prefix}-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }
  throttle_settings {
    rate_limit  = 5
    burst_limit = 10
  }
  quota_settings {
    limit  = 500
    period = "DAY"
  }
}

resource "aws_api_gateway_usage_plan_key" "key" {
  key_id        = aws_api_gateway_api_key.key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.plan.id
}
