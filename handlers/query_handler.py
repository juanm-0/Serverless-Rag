"""Query Lambda: API Gateway event -> grounded, cited answer (JSON)."""
from __future__ import annotations

import json

from app.config import env, load_secrets_from_ssm


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
    body = json.loads(event.get("body") or "{}")
    question = body.get("question")
    if not question:
        return _response(400, {"error": "missing 'question'"})

    from app.providers.vectorstore import S3DynamoVectorStore
    from app.query import answer_query

    bucket = env("INDEX_BUCKET")
    table = env("CHUNKS_TABLE")
    try:
        store = S3DynamoVectorStore.load_for_search(bucket, table)
    except Exception:
        return _response(409, {"error": "no index found — run ingest first"})

    result = answer_query(
        store, _make_embedder(), _make_llm(), question, k=int(body.get("k", 8))
    )
    return _response(200, result)
