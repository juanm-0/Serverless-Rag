import json
from pathlib import Path

import boto3
from moto import mock_aws

import handlers.ingest_handler as ih
from app.providers.vectorstore import S3DynamoVectorStore

BUCKET = "rag-index-test"
TABLE = "chunks-test"
REGION = "ca-central-1"


class _FakeEmbedder:
    def embed(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _make_repo(root: Path):
    (root / "a.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "b.md").write_text("# Title\n", encoding="utf-8")


def _configure(monkeypatch, local_path):
    monkeypatch.setenv("INDEX_BUCKET", BUCKET)
    monkeypatch.setenv("CHUNKS_TABLE", TABLE)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setattr(ih, "_load_secrets", lambda: None)
    monkeypatch.setattr(ih, "_make_embedder", lambda: _FakeEmbedder())
    # resolve_source normally clones a URL; for the test, point at a local dir
    monkeypatch.setattr(ih, "_resolve_source", lambda repo_url: local_path)


@mock_aws
def test_ingest_handler_builds_and_persists_index(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    dynamo = boto3.client("dynamodb", region_name=REGION)
    dynamo.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _configure(monkeypatch, tmp_path)

    result = ih.handler({"repo_url": "https://example.com/x.git"}, None)
    assert result["indexed_chunks"] == 2

    # the index is now queryable from S3 + DynamoDB
    loaded = S3DynamoVectorStore.load_for_search(BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo)
    hits = loaded.search([8.0, 1.0], k=2)
    assert sorted(h["chunk"]["path"] for h in hits) == ["a.py", "b.md"]
