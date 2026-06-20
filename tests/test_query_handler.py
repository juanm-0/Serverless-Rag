import json

import boto3
from moto import mock_aws

import handlers.query_handler as qh
from app.providers.vectorstore import S3DynamoVectorStore

BUCKET = "rag-index-test"
TABLE = "chunks-test"
REGION = "ca-central-1"


class _FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeLLM:
    last_usage = {"input": 1, "output": 1}

    def generate(self, system, user):
        return '{"answer": "A.", "used_block_ids": ["f.py:1-1"], "refused": false}'


def _seed_index(s3, dynamo):
    s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    dynamo.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    store = S3DynamoVectorStore(BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo)
    store.add(
        [{"id": "f.py:1-1", "path": "f.py", "start_line": 1, "end_line": 1, "text": "code"}],
        [[1.0, 0.0]],
    )
    store.persist()


def _configure(monkeypatch):
    monkeypatch.setenv("INDEX_BUCKET", BUCKET)
    monkeypatch.setenv("CHUNKS_TABLE", TABLE)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setattr(qh, "_load_secrets", lambda: None)
    monkeypatch.setattr(qh, "_make_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(qh, "_make_llm", lambda: _FakeLLM())


@mock_aws
def test_query_handler_returns_grounded_result(monkeypatch):
    s3 = boto3.client("s3", region_name=REGION)
    dynamo = boto3.client("dynamodb", region_name=REGION)
    _seed_index(s3, dynamo)
    _configure(monkeypatch)

    event = {"body": json.dumps({"question": "where?", "k": 3})}
    resp = qh.handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["answer"] == "A."
    assert body["citations"] == [{"path": "f.py", "start_line": 1, "end_line": 1}]
    assert body["refused"] is False


@mock_aws
def test_query_handler_missing_question_is_400(monkeypatch):
    _configure(monkeypatch)
    resp = qh.handler({"body": json.dumps({})}, None)
    assert resp["statusCode"] == 400


@mock_aws
def test_query_handler_no_index_is_409(monkeypatch):
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    dynamo = boto3.client("dynamodb", region_name=REGION)
    dynamo.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    _configure(monkeypatch)
    resp = qh.handler({"body": json.dumps({"question": "where?"})}, None)
    assert resp["statusCode"] == 409
