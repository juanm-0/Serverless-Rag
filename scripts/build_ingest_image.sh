#!/usr/bin/env bash
# Build the ingest container image, push to ECR, and (if the function exists)
# roll the Lambda to the new image. Run from the repo root.
set -euo pipefail
ACCOUNT="${AWS_ACCOUNT_ID:-585242447302}"
REGION="${AWS_REGION:-ca-central-1}"
REPO="serverless-rag-ingest"
TAG="${IMAGE_TAG:-latest}"
URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
docker build -f infra/ingest.Dockerfile -t "${URI}:${TAG}" .
docker push "${URI}:${TAG}"

# Roll the Lambda to the freshly-pushed image — but only if it already exists
# AND is an Image package (during the initial zip->image switch, Terraform does
# the conversion; trying to update-function-code on a zip function errors).
pkg_type="$(aws lambda get-function --function-name "${REPO}" --region "$REGION" \
  --query 'Configuration.PackageType' --output text 2>/dev/null || true)"
if [ "$pkg_type" = "Image" ]; then
  aws lambda update-function-code --function-name "${REPO}" \
    --image-uri "${URI}:${TAG}" --publish --region "$REGION" >/dev/null
  echo "rolled ${REPO} Lambda to ${URI}:${TAG}"
fi
echo "pushed ${URI}:${TAG}"
