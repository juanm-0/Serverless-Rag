# Phase 1A — Cloud Application Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cloud-backed provider implementations and Lambda handlers so the existing Phase 0 RAG core can run on AWS — all unit-tested locally with `moto` (no AWS account or deploy needed).

**Architecture:** Add a Gemini `EmbeddingProvider`, an S3+DynamoDB `VectorStore` (vectors as an S3 blob, chunk text in DynamoDB, top-k fetched via `BatchGetItem`), an SSM secret loader, and two thin Lambda handlers that adapt API Gateway events to the unchanged `app/` functions. The next plan (Phase 1B) provisions the AWS resources and deploys these.

**Tech Stack:** Python 3.11+, `boto3` (AWS SDK), `moto` (mocks AWS in tests), `google-genai` (Gemini embeddings, already installed), `numpy`, `pytest`.

**Spec:** [`docs/superpowers/specs/2026-06-19-phase1-serverless-mvp-design.md`](../specs/2026-06-19-phase1-serverless-mvp-design.md).

**Code-review checkpoint:** one review at the end of this plan (after the handlers), per the Phase 0 convention.

---

## Conventions for the implementer

- Run from repo root `F:\Work\Side\ServerlessRag\Serverless-Rag`.
- **Windows:** invoke Python only via `.venv\Scripts\python.exe` (bare `python` is a broken Store stub). Run tests with `.venv\Scripts\python.exe -m pytest <args>`.
- These tasks need **no AWS account, no network, no API keys** — `moto` mocks S3/DynamoDB/SSM, and the Gemini/Groq clients are faked in tests.
- Don't import a vendor SDK (`boto3`, `google-genai`, `anthropic`, `groq`) outside `app/providers/`, `app/config.py`, or `handlers/` (the cloud entry points). Core `app/` logic stays vendor-free.
- Modern type hints (`list[str]`, `str | None`).

---

## File structure (Plan A)

```
pyproject.toml                  # add boto3, moto
app/
  config.py                     # NEW: load secrets from SSM; env() helper
  providers/
    embeddings.py               # MODIFY: add GeminiEmbeddings
    vectorstore.py              # MODIFY: add S3DynamoVectorStore
handlers/
  __init__.py                   # NEW (empty)
  query_handler.py              # NEW: API Gateway -> app.query
  ingest_handler.py             # NEW: API Gateway (async) -> app.ingest
tests/
  test_gemini_embeddings.py     # NEW
  test_cloud_vectorstore.py     # NEW (moto)
  test_config.py                # NEW (moto/fake)
  test_query_handler.py         # NEW
  test_ingest_handler.py        # NEW
```

---

## Task 1: Add cloud dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add boto3 + moto to pyproject.toml**

In `[project] dependencies`, add `boto3` after `python-dotenv`:
```toml
    "python-dotenv>=1.0",
    "boto3>=1.34",
```
In `[project.optional-dependencies] dev`, add `moto`:
```toml
dev = ["pytest>=8.0", "moto>=5.0"]
```

- [ ] **Step 2: Install**

Run: `.venv\Scripts\python.exe -m pip install -e ".[dev]"`
Expected: completes; `boto3` and `moto` installed.

- [ ] **Step 3: Verify imports**

Run: `.venv\Scripts\python.exe -c "import boto3, moto; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Confirm existing suite still green**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all existing tests pass (37).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add boto3 + moto for the cloud app layer"
```

---

## Task 2: Gemini embedding provider

**Files:**
- Modify: `app/providers/embeddings.py`
- Test: `tests/test_gemini_embeddings.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gemini_embeddings.py`:
```python
from app.providers.embeddings import GeminiEmbeddings


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeResponse:
    def __init__(self, vectors):
        self.embeddings = [_FakeEmbedding(v) for v in vectors]


class _FakeModels:
    def __init__(self):
        self.last_kwargs = None

    def embed_content(self, **kwargs):
        self.last_kwargs = kwargs
        # one 2-d vector per input text
        texts = kwargs["contents"]
        return _FakeResponse([[float(len(t)), 1.0] for t in texts])


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_embed_returns_one_vector_per_text():
    client = _FakeClient()
    emb = GeminiEmbeddings(client=client, model="text-embedding-004")
    vecs = emb.embed(["a", "bbb"])
    assert vecs == [[1.0, 1.0], [3.0, 1.0]]
    assert client.models.last_kwargs["model"] == "text-embedding-004"
    assert client.models.last_kwargs["contents"] == ["a", "bbb"]


def test_embed_returns_plain_python_floats():
    emb = GeminiEmbeddings(client=_FakeClient())
    vecs = emb.embed(["x"])
    assert isinstance(vecs[0][0], float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_gemini_embeddings.py -q`
Expected: FAIL with `ImportError: cannot import name 'GeminiEmbeddings'`.

- [ ] **Step 3: Add `GeminiEmbeddings` to `app/providers/embeddings.py`**

Append to the file:
```python
DEFAULT_GEMINI_EMBED_MODEL = "text-embedding-004"


class GeminiEmbeddings:
    """Hosted embeddings via Google Gemini (google-genai).

    Reads GEMINI_API_KEY (or GOOGLE_API_KEY). Pass `client=` to inject a fake.
    """

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        import os

        self.model = model or os.environ.get("GEMINI_EMBED_MODEL", DEFAULT_GEMINI_EMBED_MODEL)
        if client is not None:
            self._client = client
        else:
            from google import genai  # lazy import; reads GEMINI_API_KEY / GOOGLE_API_KEY

            self._client = genai.Client()

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.models.embed_content(model=self.model, contents=texts)
        return [[float(x) for x in e.values] for e in response.embeddings]
```

> Note: `app/providers/embeddings.py` already imports `numpy as np` and `from typing import Any` at the top from Phase 0 — reuse them; do not duplicate imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_gemini_embeddings.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/providers/embeddings.py tests/test_gemini_embeddings.py
git commit -m "feat: add Gemini embedding provider"
```

---

## Task 3: S3 + DynamoDB vector store

Vectors persist as an S3 blob; chunk text/metadata in DynamoDB; query loads vectors from S3, does cosine in memory, then `BatchGetItem`s only the top-k chunks.

**Files:**
- Modify: `app/providers/vectorstore.py`
- Test: `tests/test_cloud_vectorstore.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cloud_vectorstore.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cloud_vectorstore.py -q`
Expected: FAIL with `ImportError: cannot import name 'S3DynamoVectorStore'`.

- [ ] **Step 3: Add `S3DynamoVectorStore` to `app/providers/vectorstore.py`**

Append to the file (it already imports `json`, `numpy as np`, and `from app.types import Chunk, Hit` — reuse them; add `from io import BytesIO` at the top with the other imports):
```python
_VECTORS_KEY = "index/vectors.npy"
_IDS_KEY = "index/chunk_ids.json"
_DDB_BATCH_WRITE = 25   # DynamoDB BatchWriteItem max items per request
_DDB_BATCH_GET = 100    # DynamoDB BatchGetItem max keys per request


class S3DynamoVectorStore:
    """VectorStore backed by S3 (vectors blob) + DynamoDB (chunk records).

    Ingest: add() then persist() -> writes vectors+ids to S3, chunks to DynamoDB.
    Query:  load_for_search() -> loads vectors+ids from S3; search() does cosine
            in memory and BatchGetItem-fetches only the top-k chunk records.
    """

    def __init__(self, bucket, chunks_table, s3_client=None, dynamo_client=None) -> None:
        import boto3

        self._bucket = bucket
        self._table = chunks_table
        self._s3 = s3_client or boto3.client("s3")
        self._dynamo = dynamo_client or boto3.client("dynamodb")
        self._chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None
        self._ids: list[str] = []

    # ---- ingest side ----
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must be the same length")
        if not chunks:
            return
        v = np.asarray(vectors, dtype=np.float32)
        self._vectors = v if self._vectors is None else np.vstack([self._vectors, v])
        self._chunks.extend(chunks)

    def persist(self) -> None:
        matrix = self._vectors if self._vectors is not None else np.zeros((0, 0), dtype=np.float32)
        buf = BytesIO()
        np.save(buf, matrix)
        self._s3.put_object(Bucket=self._bucket, Key=_VECTORS_KEY, Body=buf.getvalue())
        ids = [c["id"] for c in self._chunks]
        self._s3.put_object(
            Bucket=self._bucket, Key=_IDS_KEY, Body=json.dumps(ids).encode("utf-8")
        )
        for i in range(0, len(self._chunks), _DDB_BATCH_WRITE):
            batch = self._chunks[i : i + _DDB_BATCH_WRITE]
            self._dynamo.batch_write_item(
                RequestItems={
                    self._table: [
                        {
                            "PutRequest": {
                                "Item": {
                                    "id": {"S": c["id"]},
                                    "path": {"S": c["path"]},
                                    "start_line": {"N": str(c["start_line"])},
                                    "end_line": {"N": str(c["end_line"])},
                                    "text": {"S": c["text"]},
                                }
                            }
                        }
                        for c in batch
                    ]
                }
            )

    # ---- query side ----
    @classmethod
    def load_for_search(cls, bucket, chunks_table, s3_client=None, dynamo_client=None) -> "S3DynamoVectorStore":
        store = cls(bucket, chunks_table, s3_client=s3_client, dynamo_client=dynamo_client)
        vec_obj = store._s3.get_object(Bucket=bucket, Key=_VECTORS_KEY)
        store._vectors = np.load(BytesIO(vec_obj["Body"].read()))
        ids_obj = store._s3.get_object(Bucket=bucket, Key=_IDS_KEY)
        store._ids = json.loads(ids_obj["Body"].read())
        return store

    def search(self, query_vector: list[float], k: int) -> list[Hit]:
        if self._vectors is None or self._vectors.shape[0] == 0 or not self._ids:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-10)
        mat = self._vectors / (np.linalg.norm(self._vectors, axis=1, keepdims=True) + 1e-10)
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        top_ids = [self._ids[i] for i in top]
        by_id = self._batch_get_chunks(top_ids)
        hits: list[Hit] = []
        for i in top:
            chunk = by_id.get(self._ids[i])
            if chunk is not None:
                hits.append(Hit(chunk=chunk, score=float(scores[i])))
        return hits

    def _batch_get_chunks(self, ids: list[str]) -> dict[str, Chunk]:
        result: dict[str, Chunk] = {}
        for i in range(0, len(ids), _DDB_BATCH_GET):
            batch = ids[i : i + _DDB_BATCH_GET]
            resp = self._dynamo.batch_get_item(
                RequestItems={self._table: {"Keys": [{"id": {"S": cid}} for cid in batch]}}
            )
            for item in resp["Responses"].get(self._table, []):
                result[item["id"]["S"]] = Chunk(
                    id=item["id"]["S"],
                    path=item["path"]["S"],
                    start_line=int(item["start_line"]["N"]),
                    end_line=int(item["end_line"]["N"]),
                    text=item["text"]["S"],
                )
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cloud_vectorstore.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/providers/vectorstore.py tests/test_cloud_vectorstore.py
git commit -m "feat: add S3 + DynamoDB vector store"
```

---

## Task 4: Config / SSM secret loader

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os

import pytest

from app.config import env, load_secrets_from_ssm, SSM_PARAMETERS


class _FakeSSM:
    def __init__(self, values):
        self._values = values
        self.calls = []

    def get_parameter(self, Name, WithDecryption):
        self.calls.append((Name, WithDecryption))
        return {"Parameter": {"Value": self._values[Name]}}


def test_load_secrets_sets_env_from_ssm(monkeypatch):
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    fake = _FakeSSM(
        {
            "/serverless-rag/groq-api-key": "gsk_fake",
            "/serverless-rag/gemini-api-key": "gem_fake",
        }
    )
    load_secrets_from_ssm(ssm_client=fake)
    assert os.environ["GROQ_API_KEY"] == "gsk_fake"
    assert os.environ["GEMINI_API_KEY"] == "gem_fake"
    # decryption was requested
    assert all(decrypt is True for _name, decrypt in fake.calls)


def test_load_secrets_does_not_overwrite_existing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "already-set")
    monkeypatch.setenv("GEMINI_API_KEY", "already-set")
    fake = _FakeSSM({})  # would KeyError if it tried to fetch
    load_secrets_from_ssm(ssm_client=fake)
    assert os.environ["GROQ_API_KEY"] == "already-set"
    assert fake.calls == []  # nothing fetched


def test_env_returns_value_and_raises_when_missing(monkeypatch):
    monkeypatch.setenv("INDEX_BUCKET", "my-bucket")
    assert env("INDEX_BUCKET") == "my-bucket"
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(KeyError):
        env("MISSING_VAR")


def test_ssm_parameter_map_shape():
    assert SSM_PARAMETERS == {
        "/serverless-rag/groq-api-key": "GROQ_API_KEY",
        "/serverless-rag/gemini-api-key": "GEMINI_API_KEY",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Write `app/config.py`**

```python
"""Cloud config: load provider secrets from SSM, and read required env vars.

In Lambda, secrets live in SSM SecureString parameters and are fetched at cold
start (then cached in the process env). Locally, .env already populates these,
so load_secrets_from_ssm() is a no-op when the env var is already set.
"""
from __future__ import annotations

import os
from typing import Any

SSM_PARAMETERS = {
    "/serverless-rag/groq-api-key": "GROQ_API_KEY",
    "/serverless-rag/gemini-api-key": "GEMINI_API_KEY",
}


def load_secrets_from_ssm(ssm_client: Any | None = None) -> None:
    """Populate provider API keys from SSM into os.environ (idempotent).

    Only fetches a parameter when its target env var is not already set, so
    local .env values win and repeated warm invocations skip the call.
    """
    missing = {name: var for name, var in SSM_PARAMETERS.items() if not os.environ.get(var)}
    if not missing:
        return
    if ssm_client is None:
        import boto3

        ssm_client = boto3.client("ssm")
    for name, var in missing.items():
        resp = ssm_client.get_parameter(Name=name, WithDecryption=True)
        os.environ[var] = resp["Parameter"]["Value"]


def env(name: str) -> str:
    """Return a required environment variable or raise KeyError with a clear name."""
    try:
        return os.environ[name]
    except KeyError:
        raise KeyError(f"required environment variable {name!r} is not set") from None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add SSM secret loader and env helper"
```

---

## Task 5: Query Lambda handler

**Files:**
- Create: `handlers/__init__.py` (empty)
- Create: `handlers/query_handler.py`
- Test: `tests/test_query_handler.py`

- [ ] **Step 1: Create the empty package marker**

Create `handlers/__init__.py` as an **empty** file.

- [ ] **Step 2: Write the failing test**

`tests/test_query_handler.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_query_handler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'handlers.query_handler'`.

- [ ] **Step 4: Write `handlers/query_handler.py`**

Provider construction is wrapped in tiny module-level seams (`_load_secrets`, `_make_embedder`, `_make_llm`) so tests can monkeypatch them without real keys.

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_query_handler.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add handlers/__init__.py handlers/query_handler.py tests/test_query_handler.py
git commit -m "feat: add query Lambda handler"
```

---

## Task 6: Ingest Lambda handler

**Files:**
- Create: `handlers/ingest_handler.py`
- Test: `tests/test_ingest_handler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ingest_handler.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest_handler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'handlers.ingest_handler'`.

- [ ] **Step 3: Write `handlers/ingest_handler.py`**

This handler is invoked **asynchronously** (API Gateway returns 202 separately, configured in Plan 1B); it does the work and logs/returns a summary.

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest_handler.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add handlers/ingest_handler.py tests/test_ingest_handler.py
git commit -m "feat: add ingest Lambda handler"
```

---

## ✅ Code-review checkpoint — cloud app layer

- [ ] **Step 1: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all tests pass (37 from Phase 0 + ~13 new ≈ 50).

- [ ] **Step 2: Request a code review**

Invoke `superpowers:requesting-code-review` (or `/code-review`) on the diff since the Phase 1A start. Focus areas: the S3/DynamoDB serialization round-trip (numpy via BytesIO, the DynamoDB attribute-type mapping `{"S"}`/`{"N"}`, batch-size chunking for write/get), the handler seams + status codes (400/409/200), idempotent SSM loading, and that no vendor SDK leaked into core `app/` logic.

- [ ] **Step 3: Address findings**, re-run `pytest -q`, commit, then this plan is done.

---

## Self-review (plan author)

- **Spec coverage (Plan A portion of the Phase 1 spec):** §4 GeminiEmbeddings → Task 2 ✓; §4 cloud VectorStore (S3 vectors + DynamoDB chunks, BatchGetItem top-k) → Task 3 ✓; §4/§7 SSM secret loading → Task 4 ✓; §4 handlers (query sync result shape, ingest worker) → Tasks 5–6 ✓; §9 testing with moto + injected fakes → every task ✓; §12 deps (boto3, moto) → Task 1 ✓. **Deferred to Plan 1B (infra/delivery):** §6 Terraform resources, §5 the API-Gateway-returns-202 async wiring, §10 CI/CD, §11 manual bootstrap, §13 live deploy/verify. Noted intentionally — Plan A is the locally-testable code layer.
- **Placeholder scan:** none — every task has concrete test + impl code and exact commands.
- **Type consistency:** `S3DynamoVectorStore(bucket, chunks_table, s3_client=, dynamo_client=)`, `.add()/.persist()/.load_for_search()/.search()` used identically across Tasks 3, 5, 6; `GeminiEmbeddings(client=, model=)` and `.embed()` consistent across Tasks 2, 5, 6; `load_secrets_from_ssm(ssm_client=)`, `env()`, `SSM_PARAMETERS` consistent across Task 4 and the handlers; handler seams `_load_secrets`/`_make_embedder`/`_make_llm`/`_resolve_source` match between impl and tests. Chunk dict shape (`id/path/start_line/end_line/text`) matches `app/types.Chunk` throughout.
