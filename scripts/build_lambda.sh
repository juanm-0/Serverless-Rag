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
