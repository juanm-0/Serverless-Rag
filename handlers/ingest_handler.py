"""Ingest Lambda (async): clone+chunk+embed a repo into S3 + DynamoDB."""
from __future__ import annotations

from app.config import env, load_secrets_from_ssm


def _load_secrets() -> None:
    load_secrets_from_ssm()


def _make_embedder():
    from app.providers.embeddings import GeminiEmbeddings

    return GeminiEmbeddings()


def _resolve_source(repo_url: str):
    from app.ingest import resolve_source

    return resolve_source(repo_url=repo_url)


def handler(event, context):
    _load_secrets()
    repo_url = event.get("repo_url")
    if not repo_url:
        raise ValueError("event missing 'repo_url'")

    from app.ingest import build_index
    from app.providers.vectorstore import S3DynamoVectorStore

    bucket = env("INDEX_BUCKET")
    table = env("CHUNKS_TABLE")
    root = _resolve_source(repo_url)
    store = S3DynamoVectorStore(bucket, table)
    n = build_index(root, _make_embedder(), store)
    store.persist()
    print(f"ingest complete: {n} chunks from {repo_url} -> s3://{bucket}, dynamodb:{table}")
    return {"indexed_chunks": n}
