# Container-Image Ingest Lambda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is infra/packaging, not TDD.** The "test" for most tasks is `docker build`, `terraform validate`/`plan`/`apply`, and a live `POST /ingest`. Several steps are **interactive** (Docker build/push, terraform apply, live test) — marked **[RUN]**. No `app/` code changes are needed: the ingest handler already does clone→chunk→embed→store; it just needs `git` in the runtime.

**Goal:** Make `POST /ingest {repo_url}` run entirely in AWS by repackaging the ingest Lambda as a **container image** (python3.12 + `git` + deps + code) in ECR — retiring the local-clone workaround so cloud ingest is truly serverless.

**Architecture:** Keep the query Lambda as a zip. Build an ingest container image from the AWS Lambda python base + `git`, push it to a private ECR repo, and point the ingest Lambda at it (`package_type = "Image"`). Local Docker handles the bootstrap + dev builds; CI builds + pushes on every deploy.

**Tech Stack:** Docker, Amazon ECR, AWS Lambda container images, Terraform, AWS CLI, GitHub Actions.

**Spec:** extends [`docs/superpowers/specs/2026-06-19-phase1-serverless-mvp-design.md`](../specs/2026-06-19-phase1-serverless-mvp-design.md) (closes the documented "no `git` in the Lambda runtime" gap).

**Known boundary (call it out, don't hide it):** the ingest Lambda has a hard **15-minute** max. With Gemini's free-tier 429 back-off, a *large* repo can approach/exceed it. This path targets **small-to-moderate repos**; very large ones remain future work (Fargate/SQS-chunked ingestion).

---

## Fixed facts

- Account **585242447302** · region **ca-central-1** · prefix **serverless-rag** · repo **juanm-0/Serverless-Rag**
- AWS CLI: `C:\Program Files\Amazon\AWSCLIV2\aws.exe` · Terraform: `…\WinGet\Packages\Hashicorp.Terraform_…\terraform.exe`
- Docker Desktop is installed locally.
- Ingest handler entrypoint: `handlers.ingest_handler.handler` (unchanged).

---

## File structure

```
infra/
  ingest.Dockerfile     # NEW: python3.12 + git + deps + app/handlers
  ecr.tf                # NEW: ECR repo for the ingest image
  lambda.tf             # MODIFY: ingest Lambda -> package_type=Image (query stays zip)
  variables.tf          # MODIFY: add ingest_image_tag
scripts/
  build_ingest_image.sh # NEW: docker build + push + roll the Lambda
.github/workflows/
  deploy.yml            # MODIFY: build+push the ingest image during deploy
```

---

## Task 1: [RUN] Confirm Docker works

- [ ] **Step 1: Verify Docker is running**

Run: `docker version`
Expected: both Client and Server sections print (Server = the daemon is up). If "Cannot connect to the Docker daemon", start Docker Desktop and retry.

---

## Task 2: Ingest container Dockerfile

**Files:**
- Create: `infra/ingest.Dockerfile`

- [ ] **Step 1: Write `infra/ingest.Dockerfile`**

```dockerfile
# AWS Lambda Python 3.12 base (Amazon Linux 2023). Brings the Lambda runtime + boto3.
FROM public.ecr.aws/lambda/python:3.12

# The whole point: git, so the handler can clone a repo URL at runtime.
RUN microdnf install -y git && microdnf clean all

# Runtime deps (boto3 is already in the base image).
RUN pip install --no-cache-dir numpy google-genai groq

# App + handler code into the Lambda task root.
COPY app ${LAMBDA_TASK_ROOT}/app
COPY handlers ${LAMBDA_TASK_ROOT}/handlers

# Handler entrypoint (module.function).
CMD ["handlers.ingest_handler.handler"]
```

> Build context note: the Dockerfile `COPY`s `app/` and `handlers/` from the **repo root**, so the build must run with the repo root as context (`-f infra/ingest.Dockerfile .`). If `microdnf` isn't found on a future base image, swap to `dnf install -y git`.

- [ ] **Step 2: Build the image locally to verify it compiles**

Run (from repo root): `docker build -f infra/ingest.Dockerfile -t serverless-rag-ingest:test .`
Expected: build succeeds; final line `naming to docker.io/library/serverless-rag-ingest:test`.

- [ ] **Step 3: Smoke-test git is present in the image**

Run: `docker run --rm --entrypoint git serverless-rag-ingest:test --version`
Expected: prints `git version 2.x`.

- [ ] **Step 4: Commit**

```bash
git add infra/ingest.Dockerfile
git commit -m "feat: add container image for the ingest Lambda (python3.12 + git)"
```

---

## Task 3: ECR repository (Terraform)

**Files:**
- Create: `infra/ecr.tf`
- Modify: `infra/variables.tf`

- [ ] **Step 1: Write `infra/ecr.tf`**

```hcl
resource "aws_ecr_repository" "ingest" {
  name                 = "${var.prefix}-ingest"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # let `terraform destroy` remove the repo even with images
  image_scanning_configuration {
    scan_on_push = true
  }
}

output "ingest_image_repo" {
  value = aws_ecr_repository.ingest.repository_url
}
```

- [ ] **Step 2: Add the image-tag variable to `infra/variables.tf`**

Append:
```hcl
variable "ingest_image_tag" {
  description = "Tag of the ingest container image in ECR"
  default     = "latest"
}
```

- [ ] **Step 3: Create the ECR repo (targeted apply — it must exist before we can push)**

Run (from `infra/`): `terraform validate && terraform apply -target=aws_ecr_repository.ingest`
Expected: creates the ECR repo; review and approve. Note the `repository_url` output (e.g. `585242447302.dkr.ecr.ca-central-1.amazonaws.com/serverless-rag-ingest`).

- [ ] **Step 4: Commit**

```bash
git add infra/ecr.tf infra/variables.tf
git commit -m "infra: ECR repository for the ingest container image"
```

---

## Task 4: Build + push script

**Files:**
- Create: `scripts/build_ingest_image.sh`

- [ ] **Step 1: Write `scripts/build_ingest_image.sh`**

```bash
#!/usr/bin/env bash
# Build the ingest container image, push to ECR, and (if the function exists)
# roll the Lambda to the new image. Run from the repo root.
set -euo pipefail
ACCOUNT="${AWS_ACCOUNT_ID:-585242447302}"
REGION="${AWS_REGION:-ca-central-1}"
REPO="serverless-rag-ingest"
TAG="${IMAGE_TAG:-latest}"
URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
docker build -f infra/ingest.Dockerfile -t "${URI}:${TAG}" .
docker push "${URI}:${TAG}"

# If the Lambda already exists, roll it to the freshly-pushed image.
if aws lambda get-function --function-name "${REPO}" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "${REPO}" --image-uri "${URI}:${TAG}" --publish --region "$REGION" >/dev/null
  echo "rolled ${REPO} Lambda to ${URI}:${TAG}"
fi
echo "pushed ${URI}:${TAG}"
```

- [ ] **Step 2: [RUN] Build + push the first image** (Lambda doesn't exist yet, so it only pushes)

Run (from repo root, full `aws` path on PATH or a fresh terminal): `bash scripts/build_ingest_image.sh`
Expected: `docker login` succeeds, image builds + pushes; ends with `pushed …/serverless-rag-ingest:latest` (no Lambda roll yet — that's expected).

- [ ] **Step 3: Commit**

```bash
git add scripts/build_ingest_image.sh
git commit -m "build: add ingest image build/push script"
```

---

## Task 5: Switch the ingest Lambda to the container image

**Files:**
- Modify: `infra/lambda.tf`

- [ ] **Step 1: Replace the `aws_lambda_function.ingest` resource in `infra/lambda.tf`**

Replace the existing zip-based ingest function (the `aws_lambda_function "ingest"` block) with this image-based one. **Leave the query Lambda, log groups, `archive_file`, and `locals` exactly as they are.**

```hcl
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
```

> Removed (image-only): `runtime`, `handler`, `filename`, `source_code_hash` — the handler comes from the image's `CMD`. The query Lambda keeps all of those (it stays a zip).

- [ ] **Step 2: Validate + plan**

Run (from `infra/`): `terraform validate && terraform plan`
Expected: validate ok; plan shows `aws_lambda_function.ingest` will be **replaced** (zip → image) — `package_type`, `image_uri` set; `runtime`/`handler`/`filename` removed. No other function changes.

- [ ] **Step 3: [RUN] Apply**

Run (from `infra/`): `terraform apply`
Expected: the ingest Lambda is recreated from the ECR image. Outputs unchanged.

- [ ] **Step 4: Commit**

```bash
git add infra/lambda.tf
git commit -m "infra: switch ingest Lambda from zip to container image"
```

---

## Task 6: [RUN] Verify cloud-side ingest works end-to-end

This is the whole point — `POST /ingest` now clones+chunks+embeds+stores **in the Lambda**.

- [ ] **Step 1: Invoke the ingest Lambda directly with a SMALL public repo** (keeps within the 15-min limit + Gemini quota)

Use a tiny repo so the demo finishes fast. Run:
```bash
aws lambda invoke --function-name serverless-rag-ingest --region ca-central-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"repo_url":"https://github.com/pallets/click"}' /tmp/ingest-out.json
cat /tmp/ingest-out.json
```
Expected: `{"indexed_chunks": N}` with N > 0. (If it times out on a larger repo, that's the 15-min boundary — use a smaller repo.)

- [ ] **Step 2: Confirm the async HTTP path returns 202**

```bash
KEY=$(aws apigateway get-api-key --api-key <api_key_id> --include-value --region ca-central-1 --query value --output text)
curl -s -o /dev/null -w "%{http_code}\n" -X POST "<invoke_url>/ingest" \
  -H "x-api-key: $KEY" -H "content-type: application/json" \
  -d '{"repo_url":"https://github.com/pallets/click"}'
```
Expected: `202`. The ingest runs in the background; watch CloudWatch logs `/aws/lambda/serverless-rag-ingest` for `ingest complete: N chunks`.

- [ ] **Step 3: Query the freshly-ingested repo via the endpoint**

```bash
curl -s -X POST "<invoke_url>/query" -H "x-api-key: $KEY" -H "content-type: application/json" \
  -d '{"question":"How are commands defined?","k":4}'
```
Expected: a grounded, cited answer from the just-ingested repo. **No local clone involved anywhere.**

- [ ] **Step 4 (no commit — this is verification).** If anything fails, check the CloudWatch logs and fix the relevant Task before proceeding.

---

## Task 7: Build + push the image in CI

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Add an image build/push step to the `deploy` job in `.github/workflows/deploy.yml`**

Insert this step in the `deploy` job **after** the `configure-aws-credentials` step and **before** the Terraform step:

```yaml
      - name: Build & push ingest image
        if: github.event_name != 'pull_request'
        run: bash scripts/build_ingest_image.sh
        env:
          AWS_REGION: ca-central-1
          AWS_ACCOUNT_ID: "585242447302"
          IMAGE_TAG: latest
```

> The runner has Docker pre-installed. On `main`, this builds+pushes the image and (since the function exists) rolls the Lambda via `update-function-code`. On PRs it's skipped (no deploy). The CI deploy role already has ECR + Lambda permissions via PowerUserAccess.

- [ ] **Step 2: Commit + push, then watch the run**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: build and push the ingest container image on deploy"
git push origin main
```
Expected: the Actions run builds the image, pushes to ECR, rolls the ingest Lambda, and Terraform apply is a no-op for it (image_uri unchanged). Confirm green with `gh run list --limit 1`.

---

## Task 8: Docs — ingest is now serverless

**Files:**
- Modify: `docs/aws-concepts-review.md`, `README.md`

- [ ] **Step 1: Update `docs/aws-concepts-review.md`** — in the "Lessons from the live deploy" list, amend item 6 (no `git` in Lambda) to note it is **resolved** by the container-image ingest Lambda (ECR), and that the query Lambda stays a zip. Add a short "Lambda zip vs container image" note (zip ≤250 MB, fast cold start, no system binaries; image ≤10 GB, can include `git`/system packages, slightly slower cold start).

- [ ] **Step 2: Update `README.md`** — in "Using your deployed endpoint", replace the local-workaround ingest block with the **real serverless** flow:
```bash
# ingest a repo entirely in the cloud (the Lambda clones+chunks+embeds+stores)
curl -s -X POST "<your-invoke-url>/ingest" -H "x-api-key: $KEY" -H "content-type: application/json" \
  -d '{"repo_url":"https://github.com/OWNER/REPO"}'   # returns 202; runs in the background
```
Keep the local CLI (`rag ingest --path .`) as the explicit **local dev** mode. Note the 15-min ingest boundary for large repos.

- [ ] **Step 3: Commit + push**

```bash
git add docs/aws-concepts-review.md README.md
git commit -m "docs: ingest is now serverless via the container-image Lambda"
git push origin main
```

---

## ✅ Final checkpoint

- [ ] **Step 1: Verify the exit criterion with evidence** (`superpowers:verification-before-completion`): `POST /ingest {repo_url}` returns 202, the ingest Lambda logs `ingest complete: N chunks` in CloudWatch, and a subsequent `POST /query` returns a grounded answer about the ingested repo — **with no local clone**. Paste the evidence.
- [ ] **Step 2: Confirm cost safety** — `aws budgets describe-budgets` still shows the $1 budget; ECR storage of one small image is within free tier (500 MB/month).
- [ ] **Step 3: Confirm `terraform destroy` still round-trips** (ECR `force_delete = true` lets it remove the repo + images).

---

## Self-review (plan author)

- **Spec coverage:** closes the spec's documented "no `git` in Lambda" gap → Tasks 2–6 ✓; query Lambda stays zip (spec §6) → unchanged in Task 5 ✓; async `POST /ingest` 202 (spec §5) → unchanged integration, verified Task 6 ✓; CI deploy via OIDC (spec §10) extended for the image → Task 7 ✓; `terraform destroy` (spec §13) → ECR `force_delete`, final checkpoint ✓. The 15-min boundary is surfaced, not hidden.
- **Placeholder scan:** none — concrete Dockerfile, Terraform, script, CI, and exact commands. `<api_key_id>`/`<invoke_url>` are intentional per-user placeholders (fetched via `terraform output` / `get-api-key`), not gaps.
- **Consistency:** function name `serverless-rag-ingest`, repo name `serverless-rag-ingest`, handler `handlers.ingest_handler.handler`, image tag `latest` (var `ingest_image_tag`), region `ca-central-1`, account `585242447302` match across the Dockerfile, ecr.tf, lambda.tf, the build script, and CI. No `app/` code changes — the existing ingest handler (clone+chunk+embed+store) works once `git` exists in the runtime.
