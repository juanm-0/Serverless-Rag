import boto3
import pytest
from moto import mock_aws

from app.providers.vectorstore import S3DynamoVectorStore

BUCKET = "rag-index-test"
TABLE = "chunks-test"
REGION = "ca-central-1"


def _chunk(i):
    return {
        "id": f"f.py:{i}-{i}",
        "path": "f.py",
        "start_line": i,
        "end_line": i,
        "text": f"chunk {i}",
    }


def _setup_aws():
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(
        Bucket=BUCKET,
        CreateBucketConfiguration={"LocationConstraint": REGION},
    )
    dynamo = boto3.client("dynamodb", region_name=REGION)
    dynamo.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return s3, dynamo


@mock_aws
def test_persist_then_load_and_search_round_trips():
    s3, dynamo = _setup_aws()
    store = S3DynamoVectorStore(BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo)
    store.add([_chunk(0), _chunk(1)], [[1.0, 0.0], [0.0, 1.0]])
    store.persist()

    loaded = S3DynamoVectorStore.load_for_search(
        BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo
    )
    hits = loaded.search([0.9, 0.1], k=2)
    assert [h["chunk"]["id"] for h in hits] == ["f.py:0-0", "f.py:1-1"]
    assert hits[0]["score"] > hits[1]["score"]
    # chunk text came back from DynamoDB
    assert hits[0]["chunk"]["text"] == "chunk 0"
    assert hits[0]["chunk"]["start_line"] == 0


@mock_aws
def test_search_only_fetches_top_k_from_dynamo():
    s3, dynamo = _setup_aws()
    store = S3DynamoVectorStore(BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo)
    store.add(
        [_chunk(0), _chunk(1), _chunk(2)],
        [[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]],
    )
    store.persist()
    loaded = S3DynamoVectorStore.load_for_search(
        BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo
    )
    hits = loaded.search([1.0, 0.0], k=1)
    assert len(hits) == 1
    assert hits[0]["chunk"]["id"] == "f.py:0-0"


@mock_aws
def test_search_on_missing_index_raises_for_handler_to_catch():
    _setup_aws()
    s3 = boto3.client("s3", region_name=REGION)
    dynamo = boto3.client("dynamodb", region_name=REGION)
    with pytest.raises(Exception):
        S3DynamoVectorStore.load_for_search(BUCKET, TABLE, s3_client=s3, dynamo_client=dynamo)


# --- DynamoDB partial-success retries (moto never returns Unprocessed*) -------

class _FlakyWriteDynamo:
    """Returns ALL items as UnprocessedItems on the first call, then succeeds."""

    def __init__(self):
        self.calls = 0

    def batch_write_item(self, RequestItems):
        self.calls += 1
        if self.calls == 1:
            return {"UnprocessedItems": RequestItems}
        return {"UnprocessedItems": {}}


class _FlakyGetDynamo:
    """Returns nothing + UnprocessedKeys on the first call, then the items."""

    def __init__(self, items):
        self.calls = 0
        self._items = items

    def batch_get_item(self, RequestItems):
        self.calls += 1
        if self.calls == 1:
            return {"Responses": {TABLE: []}, "UnprocessedKeys": RequestItems}
        return {"Responses": {TABLE: self._items}, "UnprocessedKeys": {}}


def test_batch_write_retries_unprocessed_items(monkeypatch):
    monkeypatch.setattr("app.providers.vectorstore.time.sleep", lambda *_a: None)
    fake = _FlakyWriteDynamo()
    store = S3DynamoVectorStore(BUCKET, TABLE, s3_client=object(), dynamo_client=fake)
    store._batch_write_with_retry({TABLE: [{"PutRequest": {"Item": {"id": {"S": "x"}}}}]})
    assert fake.calls == 2  # first call's UnprocessedItems were retried


def test_batch_get_retries_unprocessed_keys(monkeypatch):
    monkeypatch.setattr("app.providers.vectorstore.time.sleep", lambda *_a: None)
    item = {
        "id": {"S": "f.py:1-1"},
        "path": {"S": "f.py"},
        "start_line": {"N": "1"},
        "end_line": {"N": "1"},
        "text": {"S": "code"},
    }
    fake = _FlakyGetDynamo([item])
    store = S3DynamoVectorStore(BUCKET, TABLE, s3_client=object(), dynamo_client=fake)
    got = store._batch_get_with_retry({TABLE: {"Keys": [{"id": {"S": "f.py:1-1"}}]}})
    assert fake.calls == 2
    assert got == [item]
