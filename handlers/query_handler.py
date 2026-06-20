"""Query Lambda: API Gateway event -> grounded, cited answer (JSON)."""
from __future__ import annotations

import json

from botocore.exceptions import ClientError

from app.config import env, load_secrets_from_ssm

# S3 error codes that mean "the index objects aren't there yet" (run ingest).
_NO_INDEX_S3_CODES = {"NoSuchKey", "NoSuchBucket", "404"}


def _load_secrets() -> None:
    load_secrets_from_ssm()


def _make_embedder():
    from app.providers.embeddings import GeminiEmbeddings

    return GeminiEmbeddings()


def _make_llm():
    from app.providers.llm import make_llm

    return make_llm()


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    _load_secrets()
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "invalid JSON body"})
    question = body.get("question")
    if not question:
        return _response(400, {"error": "missing 'question'"})

    from app.providers.vectorstore import S3DynamoVectorStore
    from app.query import answer_query

    bucket = env("INDEX_BUCKET")
    table = env("CHUNKS_TABLE")
    try:
        store = S3DynamoVectorStore.load_for_search(bucket, table)
    except ClientError as e:
        # Only a genuinely-missing index is a 409; real failures (permissions,
        # region, corrupt data) must surface as 500 rather than be mislabeled.
        if e.response.get("Error", {}).get("Code") in _NO_INDEX_S3_CODES:
            return _response(409, {"error": "no index found — run ingest first"})
        return _response(500, {"error": "failed to load index"})

    result = answer_query(
        store, _make_embedder(), _make_llm(), question, k=int(body.get("k", 8))
    )
    return _response(200, result)
