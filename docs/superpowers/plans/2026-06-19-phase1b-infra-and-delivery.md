# Phase 1B — Infrastructure & Delivery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is infra-heavy, not TDD.** The "test" for most tasks is `terraform validate` / `plan` / `apply` and a live `curl`, not pytest. Several tasks require **interactive AWS actions by the human** (creating keys, running CLI bootstrap) — those are clearly marked **[MANUAL]** and must be done by the user, not a subagent.

**Goal:** Provision the Phase 1 AWS infrastructure with Terraform and deploy the Phase 1A cloud code so `POST /query` returns a grounded, cited answer from AWS, deployable via CI and destroyable with one command.

**Architecture:** Terraform (S3+DynamoDB remote state) provisions an S3 index bucket, two DynamoDB tables, two zip Lambdas (packaged with Linux wheels), a REST API Gateway with an API-key usage plan (`/query` sync, `/ingest` async-202), least-privilege IAM, SSM SecureString secrets (set out-of-band), and CloudWatch log groups (30-day retention). GitHub Actions deploys via OIDC after a one-time local bootstrap apply.

**Tech Stack:** Terraform, AWS (Lambda, S3, DynamoDB, API Gateway REST, IAM, SSM, CloudWatch), AWS CLI, GitHub Actions + OIDC, Python 3.12 Lambda runtime.

**Spec:** [`docs/superpowers/specs/2026-06-19-phase1-serverless-mvp-design.md`](../specs/2026-06-19-phase1-serverless-mvp-design.md). Depends on Plan 1A (cloud code) being complete.

**Code-review/verification checkpoints:** a security review of the IAM + a final verification of the live exit criterion.

---

## Fixed facts (use these literally)

- AWS account: **585242447302** · region: **ca-central-1** · profile: default (`juanm-admin`)
- GitHub repo: **juanm-0/Serverless-Rag**
- Project prefix: **serverless-rag**
- AWS CLI: `C:\Program Files\Amazon\AWSCLIV2\aws.exe` (bare `aws` works in a fresh terminal)
- Python: `.venv\Scripts\python.exe`
- Lambda runtime: **python3.12**; handlers: `handlers.query_handler.handler`, `handlers.ingest_handler.handler`
- SSM parameter names: `/serverless-rag/groq-api-key`, `/serverless-rag/gemini-api-key`

---

## File structure (Plan 1B)

```
infra/
  versions.tf        # terraform + AWS provider versions; S3 remote backend
  variables.tf       # region, prefix, account id, github repo
  storage.tf         # S3 index bucket; DynamoDB chunks + eval_results tables
  secrets.tf         # SSM SecureString data sources (values set out-of-band)
  iam.tf             # Lambda execution roles + least-privilege policies; APIGW->Lambda role
  lambda.tf          # build packaging + the two Lambda functions + CloudWatch log groups
  apigw.tf           # REST API; /query (sync proxy); /ingest (async 202); usage plan + key; stage
  oidc.tf            # GitHub OIDC provider + CI deploy role
  outputs.tf         # invoke URL, api key id, table/bucket names
  build/             # generated Lambda package (gitignored)
scripts/
  build_lambda.sh    # builds the deployment package with Linux wheels (cross-platform)
.github/workflows/
  deploy.yml         # CI: tests + plan on PR; apply on main (OIDC)
```

---

## Task 0: [MANUAL] Bootstrap — keys, SSM, and remote state

**The human runs these.** A subagent cannot create accounts/keys or run interactive AWS auth. Run in Git Bash from the repo root. `aws` = a fresh terminal where it's on PATH (or the full path).

- [ ] **Step 1: Get a free Gemini API key**

Go to **https://aistudio.google.com** → **Get API key** → create one (free, no card). Copy it (starts with `AIza...`). Do NOT paste it into this chat — it goes straight into SSM in Step 3.

- [ ] **Step 2: Confirm the Groq key is handy**

You already have a Groq key (`gsk_...`) from Phase 0. Have it ready for Step 3.

- [ ] **Step 3: Put both keys into SSM as SecureString (out-of-band — never in Terraform)**

```bash
aws ssm put-parameter --name /serverless-rag/groq-api-key   --type SecureString --value "gsk_YOUR_GROQ_KEY"   --region ca-central-1
aws ssm put-parameter --name /serverless-rag/gemini-api-key --type SecureString --value "AIzaYOUR_GEMINI_KEY" --region ca-central-1
```
Verify (names only, not values):
```bash
aws ssm describe-parameters --region ca-central-1 --query "Parameters[].Name"
```
Expected: both names listed.

- [ ] **Step 4: Bootstrap the Terraform remote-state backend (S3 bucket + DynamoDB lock)**

The state bucket must exist before `terraform init`. Bucket names are globally unique — we suffix with the account id.
```bash
aws s3api create-bucket --bucket serverless-rag-tfstate-585242447302 \
  --region ca-central-1 --create-bucket-configuration LocationConstraint=ca-central-1
aws s3api put-bucket-versioning --bucket serverless-rag-tfstate-585242447302 \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket serverless-rag-tfstate-585242447302 \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws dynamodb create-table --table-name serverless-rag-tflock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region ca-central-1
```
Expected: bucket + table created. (These two resources live outside Terraform's lifecycle by design.)

- [ ] **Step 5: Report back** the two SSM names exist and the state bucket/table were created, then proceed to Task 1.

---

## Task 1: Lambda packaging script

Builds a deployment package containing the app code + **Linux** wheels (numpy, google-genai, groq pull binary wheels; building from Windows needs `--platform`). One package serves both Lambdas (they differ only by handler entrypoint).

**Files:**
- Create: `scripts/build_lambda.sh`
- Modify: `.gitignore`

- [ ] **Step 1: Write `scripts/build_lambda.sh`**

```bash
#!/usr/bin/env bash
# Build the Lambda deployment package with Linux (manylinux) wheels so it runs
# on the Amazon Linux Lambda runtime regardless of the build host's OS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/infra/build"
PY="${PYTHON:-python}"

rm -rf "$BUILD"
mkdir -p "$BUILD"

# App + handler code (no tests, no local-only modules)
cp -r "$ROOT/app" "$BUILD/app"
cp -r "$ROOT/handlers" "$BUILD/handlers"
# Drop bytecode/caches
find "$BUILD" -type d -name __pycache__ -prune -exec rm -rf {} +

# Runtime deps only (boto3 is provided by the Lambda runtime -> exclude).
# Linux cp312 wheels, even when building on Windows/macOS.
"$PY" -m pip install \
  --target "$BUILD" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: --upgrade \
  numpy google-genai groq

echo "Built package at $BUILD"
```

- [ ] **Step 2: Ignore build artifacts**

Append to `.gitignore`:
```gitignore
infra/build/
infra/.terraform/
*.tfstate
*.tfstate.*
.terraform.lock.hcl
```

- [ ] **Step 3: Run the build to verify it produces a Linux package**

Run (Git Bash): `PYTHON=.venv/Scripts/python.exe bash scripts/build_lambda.sh`
Expected: `infra/build/` contains `app/`, `handlers/`, `numpy/`, `google/`, `groq/`, and a `*.dist-info` for numpy whose wheel is `...manylinux...`. Confirm size is well under 250 MB: `du -sh infra/build` (expect tens of MB).

- [ ] **Step 4: Commit**

```bash
git add scripts/build_lambda.sh .gitignore
git commit -m "build: add cross-platform Lambda packaging script"
```

---

## Task 2: Terraform skeleton (versions, backend, variables, provider)

**Files:**
- Create: `infra/versions.tf`, `infra/variables.tf`

- [ ] **Step 1: Write `infra/versions.tf`**

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "serverless-rag-tfstate-585242447302"
    key            = "phase1/terraform.tfstate"
    region         = "ca-central-1"
    dynamodb_table = "serverless-rag-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.prefix, ManagedBy = "terraform" }
  }
}
```

- [ ] **Step 2: Write `infra/variables.tf`**

```hcl
variable "region"      { default = "ca-central-1" }
variable "prefix"      { default = "serverless-rag" }
variable "account_id"  { default = "585242447302" }
variable "github_repo" { default = "juanm-0/Serverless-Rag" }
```

- [ ] **Step 3: Initialize Terraform against the remote backend**

Run (from `infra/`): `terraform init`
Expected: "Successfully configured the backend "s3"!" and provider plugins installed. (Requires Task 0 Step 4 done.)

- [ ] **Step 4: Commit**

```bash
git add infra/versions.tf infra/variables.tf
git commit -m "infra: terraform skeleton with S3 remote backend"
```

---

## Task 3: Storage + secrets (S3, DynamoDB, SSM data sources)

**Files:**
- Create: `infra/storage.tf`, `infra/secrets.tf`

- [ ] **Step 1: Write `infra/storage.tf`**

```hcl
# Vector index blobs (vectors.npy + chunk_ids.json)
resource "aws_s3_bucket" "index" {
  bucket = "${var.prefix}-index-${var.account_id}"
}

resource "aws_s3_bucket_public_access_block" "index" {
  bucket                  = aws_s3_bucket.index.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Chunk text/metadata, keyed by chunk id
resource "aws_dynamodb_table" "chunks" {
  name         = "${var.prefix}-chunks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute { name = "id"  type = "S" }
}

# One record per eval run
resource "aws_dynamodb_table" "eval_results" {
  name         = "${var.prefix}-eval-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  attribute { name = "run_id" type = "S" }
}
```

- [ ] **Step 2: Write `infra/secrets.tf`** (reference SSM params set out-of-band; never store values)

```hcl
data "aws_ssm_parameter" "groq_key" {
  name = "/${var.prefix}/groq-api-key"
}
data "aws_ssm_parameter" "gemini_key" {
  name = "/${var.prefix}/gemini-api-key"
}
```

- [ ] **Step 3: Validate + plan**

Run (from `infra/`): `terraform validate && terraform plan`
Expected: validate succeeds; plan shows the S3 bucket + 2 DynamoDB tables to create (and reads the 2 SSM params as data sources). No errors.

- [ ] **Step 4: Commit**

```bash
git add infra/storage.tf infra/secrets.tf
git commit -m "infra: S3 index bucket, DynamoDB tables, SSM data sources"
```

---

## Task 4: IAM — least-privilege Lambda roles

**Files:**
- Create: `infra/iam.tf`

- [ ] **Step 1: Write `infra/iam.tf`**

```hcl
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service" identifiers = ["lambda.amazonaws.com"] }
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

# ---- Ingest Lambda role: query perms + write index + write chunks ----
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
```

- [ ] **Step 2: Validate + plan**

Run (from `infra/`): `terraform validate && terraform plan`
Expected: validate ok; plan adds the two roles + policies. No errors.

- [ ] **Step 3: Commit**

```bash
git add infra/iam.tf
git commit -m "infra: least-privilege IAM roles for the two Lambdas"
```

---

## Task 5: Lambda functions + log groups

**Files:**
- Create: `infra/lambda.tf`

- [ ] **Step 1: Write `infra/lambda.tf`**

```hcl
# Zip the build/ dir (populated by scripts/build_lambda.sh) into a deployable package.
data "archive_file" "package" {
  type        = "zip"
  source_dir  = "${path.module}/build"
  output_path = "${path.module}/build.zip"
}

locals {
  lambda_env = {
    INDEX_BUCKET   = aws_s3_bucket.index.bucket
    CHUNKS_TABLE   = aws_dynamodb_table.chunks.name
    LLM_PROVIDER   = "groq"
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
  environment { variables = local.lambda_env }
  depends_on       = [aws_cloudwatch_log_group.query]
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.prefix}-ingest"
  retention_in_days = 30
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.prefix}-ingest"
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.12"
  handler          = "handlers.ingest_handler.handler"
  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256
  timeout          = 900   # 15 min for async ingest
  memory_size      = 1024
  ephemeral_storage { size = 1024 }   # /tmp for git clone
  environment { variables = local.lambda_env }
  depends_on       = [aws_cloudwatch_log_group.ingest]
}
```

> **Note on `git` in the ingest Lambda:** the Amazon Linux python3.12 runtime does **not** include the `git` binary, which `app.ingest.resolve_source` shells out to for `--repo-url`. Two options, decide at execution: (a) for the demo, ingest a small repo via a Lambda **container image** later, or (b) **Phase 1 simplification** — have the ingest handler accept the target as an uploaded tarball / an already-present path rather than git-clone. Simplest for now: **document that `POST /ingest` with `repo_url` requires git** and, if not packaging git, run the one-shot ingest from your laptop against the cloud store (set `INDEX_BUCKET`/`CHUNKS_TABLE` + AWS creds locally and call the ingest handler). Flag this to the user during execution; it does not block the query path (the headline deliverable).

- [ ] **Step 2: Build the package, then validate + plan**

Run: `PYTHON=.venv/Scripts/python.exe bash scripts/build_lambda.sh` then from `infra/`: `terraform validate && terraform plan`
Expected: plan shows two Lambda functions + two log groups; the archive is built from `infra/build`.

- [ ] **Step 3: Commit**

```bash
git add infra/lambda.tf
git commit -m "infra: two Lambda functions + 30-day CloudWatch log groups"
```

---

## Task 6: API Gateway REST — /query (sync), /ingest (async 202), usage plan

**Files:**
- Create: `infra/apigw.tf`

- [ ] **Step 1: Write `infra/apigw.tf`**

```hcl
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
    principals { type = "Service" identifiers = ["apigateway.amazonaws.com"] }
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
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.ingest.arn }]
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
  rest_api_id       = aws_api_gateway_rest_api.api.id
  resource_id       = aws_api_gateway_resource.ingest.id
  http_method       = aws_api_gateway_method.ingest_post.http_method
  status_code       = aws_api_gateway_method_response.ingest_202.status_code
  selection_pattern = ""   # default mapping (Lambda async returns 202)
  response_templates = { "application/json" = jsonencode({ status = "accepted" }) }
  depends_on        = [aws_api_gateway_integration.ingest]
}

# ---------- deployment + stage ----------
resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_integration.query, aws_api_gateway_integration.ingest,
      aws_api_gateway_method.query_post, aws_api_gateway_method.ingest_post,
    ]))
  }
  lifecycle { create_before_destroy = true }
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
  throttle_settings { rate_limit = 5 burst_limit = 10 }
  quota_settings    { limit = 500 period = "DAY" }
}
resource "aws_api_gateway_usage_plan_key" "key" {
  key_id        = aws_api_gateway_api_key.key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.plan.id
}
```

- [ ] **Step 2: Validate + plan**

Run (from `infra/`): `terraform validate && terraform plan`
Expected: validate ok; plan adds the REST API, two methods/integrations, the async role, deployment, stage, usage plan + key. **This is the fiddliest file** — if `validate`/`plan` errors, fix the specific resource argument it names (API Gateway argument shapes are strict) before continuing.

- [ ] **Step 3: Commit**

```bash
git add infra/apigw.tf
git commit -m "infra: API Gateway REST with sync /query, async /ingest, usage plan"
```

---

## Task 7: GitHub OIDC provider + CI role + outputs

**Files:**
- Create: `infra/oidc.tf`, `infra/outputs.tf`

- [ ] **Step 1: Write `infra/oidc.tf`**

```hcl
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

# Deploy permissions: manage this project's resources. Scoped to the services we use.
resource "aws_iam_role_policy_attachment" "ci_power" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}
resource "aws_iam_role_policy" "ci_iam" {
  # PowerUserAccess excludes IAM; grant the specific IAM actions Terraform needs.
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Action = ["iam:*"],
      Resource = "arn:aws:iam::${var.account_id}:role/${var.prefix}-*"
    }, {
      Effect = "Allow",
      Action = ["iam:GetOpenIDConnectProvider", "iam:*OpenIDConnectProvider*"],
      Resource = "*"
    }]
  })
}
```

> Note: `PowerUserAccess` + scoped IAM keeps CI from being full admin. Tighten further later if desired; for a learning project this is a reasonable balance.

- [ ] **Step 2: Write `infra/outputs.tf`**

```hcl
output "invoke_url" {
  value = "${aws_api_gateway_stage.prod.invoke_url}"
}
output "api_key_id" {
  value = aws_api_gateway_api_key.key.id
}
output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}
output "index_bucket" { value = aws_s3_bucket.index.bucket }
output "chunks_table" { value = aws_dynamodb_table.chunks.name }
```

- [ ] **Step 3: Validate + plan**

Run (from `infra/`): `terraform validate && terraform plan`
Expected: validate ok; plan now shows the full stack. Review the resource count.

- [ ] **Step 4: Commit**

```bash
git add infra/oidc.tf infra/outputs.tf
git commit -m "infra: GitHub OIDC provider, CI deploy role, outputs"
```

---

## ✅ Security review checkpoint — IAM

- [ ] **Step 1: Request a security-focused review** of `infra/iam.tf`, `infra/oidc.tf`, and the API Gateway auth in `infra/apigw.tf`. Use `superpowers:requesting-code-review` (or `/security-review`). Focus: are the Lambda roles least-privilege (no `*` resource where an ARN works)? Is the OIDC trust `sub` correctly scoped to `repo:juanm-0/Serverless-Rag:*` (not `*`)? Is `api_key_required = true` on both methods? Is the state bucket + index bucket public-access-blocked?
- [ ] **Step 2: Address findings**, re-run `terraform validate && terraform plan`, commit.

---

## Task 8: First deploy (local) + smoke test

**[MANUAL-ish]** The first `apply` is run **locally by the user** (creates the OIDC provider + CI role that future CI deploys rely on).

- [ ] **Step 1: Build the package + apply**

```bash
PYTHON=.venv/Scripts/python.exe bash scripts/build_lambda.sh
cd infra && terraform apply   # review the plan, type yes
```
Expected: all resources create; outputs print `invoke_url`, `api_key_id`, etc.

- [ ] **Step 2: Fetch the API key value**

```bash
aws apigateway get-api-key --api-key "$(terraform -chdir=infra output -raw api_key_id)" --include-value \
  --region ca-central-1 --query value --output text
```
Keep this value local (it's a secret-ish abuse-control key) — don't paste it into chat.

- [ ] **Step 3: Build an index in the cloud** (see the `git`-in-Lambda note in Task 5). Simplest path for the demo: run the ingest locally against the cloud store —
```bash
INDEX_BUCKET=$(terraform -chdir=infra output -raw index_bucket) \
CHUNKS_TABLE=$(terraform -chdir=infra output -raw chunks_table) \
AWS_DEFAULT_REGION=ca-central-1 LLM_PROVIDER=groq \
.venv/Scripts/python.exe -c "import handlers.ingest_handler as h; print(h.handler({'repo_url':'.'}, None))"
```
(uses your local git + AWS creds to populate S3+DynamoDB). Expected: `{'indexed_chunks': N}`.

- [ ] **Step 4: Smoke-test the live query endpoint**

```bash
curl -s -X POST "$(terraform -chdir=infra output -raw invoke_url)/query" \
  -H "x-api-key: <THE_KEY_VALUE>" -H "content-type: application/json" \
  -d '{"question":"Where does line-based chunking happen?"}'
```
Expected: JSON with a grounded `answer`, `citations` referencing `app/chunk.py`, `latency_ms`, `tokens`. A missing/invalid key → `403`. **This is the Phase 1 headline: a cited answer served from AWS.**

- [ ] **Step 5: Commit any infra fixes** discovered during apply (e.g. tweaked API Gateway args).

---

## Task 9: GitHub Actions CI/CD (OIDC)

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write `.github/workflows/deploy.yml`**

```yaml
name: ci-cd
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
permissions:
  id-token: write   # required for OIDC
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -q
  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::585242447302:role/serverless-rag-ci-deploy
          aws-region: ca-central-1
      - uses: hashicorp/setup-terraform@v3
      - run: bash scripts/build_lambda.sh
      - name: terraform plan (PR) / apply (main)
        working-directory: infra
        run: |
          terraform init
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            terraform plan
          else
            terraform apply -auto-approve
          fi
```

> Note: `pip install -e ".[dev]"` in the `test` job pulls sentence-transformers/torch — fine on CI, just slow. If you want faster CI, split a lighter test-deps extra later; not required now.

- [ ] **Step 2: Commit + push, then watch the run**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: GitHub Actions deploy via OIDC (tests+plan on PR, apply on main)"
git push origin main
```
Expected: the Actions run authenticates via OIDC (no stored AWS keys), runs the 53 tests, builds the package, and `terraform apply` is a no-op/small diff (resources already exist from Task 8). Watch with `gh run watch` or the GitHub UI.

---

## Task 10: Live eval from the cloud + docs

**Files:**
- Modify: `README.md`, `docs/aws-concepts-review.md`

- [ ] **Step 1: Run the eval against the deployed endpoint** (manual). Either point `run_eval` at the cloud store (set `INDEX_BUCKET`/`CHUNKS_TABLE`/region as in Task 8 Step 3) or curl `/query` for each golden question. Capture retrieval hit-rate + answer correctness.

- [ ] **Step 2: Update `README.md`** — add a "Deployed on AWS" section: the architecture, `curl` example (with `x-api-key`), how to deploy (`terraform apply` / CI), and `terraform destroy` to tear down. Record the cloud eval number.

- [ ] **Step 3: Update `docs/aws-concepts-review.md`** — mark the decision log items as implemented; add any gotchas learned during deploy (e.g. Lambda packaging Linux wheels, `git`-in-Lambda, API Gateway async integration).

- [ ] **Step 4: Commit + push**

```bash
git add README.md docs/aws-concepts-review.md
git commit -m "docs: document AWS deployment, curl demo, and cloud eval score"
git push origin main
```

---

## ✅ Final verification checkpoint

- [ ] **Step 1: Verify the exit criterion with evidence** (use `superpowers:verification-before-completion`):
  - `curl .../query` with the key returns a grounded, cited answer from AWS (paste it).
  - The CI run on `main` deployed via OIDC (paste the run conclusion).
  - `terraform destroy` then `terraform apply` round-trips cleanly (optional but proves reproducibility).
- [ ] **Step 2: Confirm cost safety** — `aws budgets describe-budgets` still shows the $1 budget; check the Free-tier usage page shows ~zero spend.
- [ ] **Step 3: Final review** via `superpowers:requesting-code-review` on the whole Phase 1B diff; then `superpowers:finishing-a-development-branch`.

---

## Self-review (plan author)

- **Spec coverage:** §6 S3/DynamoDB/Lambdas/API Gateway/IAM/CloudWatch/SSM → Tasks 3–7 ✓; §5 async ingest 202 → Task 6 ✓; §5 sync query → Task 6 ✓; §7 SSM out-of-band secrets → Task 0 + secrets.tf ✓; §10 Terraform remote state + OIDC CI → Tasks 2,7,9 ✓; §10 30-day log retention → Task 5 ✓; §11 manual bootstrap → Task 0 ✓; §13 exit criterion (cited answer from AWS, CI deploy, destroy) → Tasks 8,10, final checkpoint ✓; §12 deps already handled in 1A. **Known gap surfaced, not hidden:** `git` is absent from the python3.12 Lambda runtime, so `POST /ingest {repo_url}` cloud-side needs a container image or a packaging workaround — Task 5 documents the workaround (run one-shot ingest locally against the cloud store) so the **query** headline still ships; full cloud-side git ingest is flagged as a follow-up.
- **Placeholder scan:** no TBDs; the two `[MANUAL]`/decision notes (git-in-Lambda, CI test-deps speed) are explicit decisions with concrete fallbacks, not vague hand-waves.
- **Consistency:** SSM names, region (ca-central-1), account (585242447302), repo (juanm-0/Serverless-Rag), prefix (serverless-rag), handler paths (`handlers.query_handler.handler` / `handlers.ingest_handler.handler`), and env vars (`INDEX_BUCKET`/`CHUNKS_TABLE`/`LLM_PROVIDER`) match Plan 1A's code (`app/config.env`, the handlers) and across all tasks. Lambda env var names match what `query_handler`/`ingest_handler` read via `env(...)`.
