"""Brute-force in-memory vector store with cosine similarity.

Persists to two files that map cleanly to S3 objects in Phase 1:
  - vectors.npy : float32 matrix, one row per chunk
  - chunks.json : list of Chunk dicts, row-aligned with the matrix
"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import numpy as np

from app.types import Chunk, Hit

_VECTORS_FILE = "vectors.npy"
_CHUNKS_FILE = "chunks.json"
_EPS = 1e-10


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None  # shape (n, d), float32

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must be the same length")
        if not chunks:
            return
        new = np.asarray(vectors, dtype=np.float32)
        self._vectors = new if self._vectors is None else np.vstack([self._vectors, new])
        self._chunks.extend(chunks)

    def search(self, query_vector: list[float], k: int) -> list[Hit]:
        if self._vectors is None or not self._chunks:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) + _EPS)
        mat = self._vectors / (np.linalg.norm(self._vectors, axis=1, keepdims=True) + _EPS)
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [Hit(chunk=self._chunks[i], score=float(scores[i])) for i in top]

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        vectors = self._vectors if self._vectors is not None else np.zeros((0, 0), dtype=np.float32)
        np.save(directory / _VECTORS_FILE, vectors)
        (directory / _CHUNKS_FILE).write_text(
            json.dumps(self._chunks), encoding="utf-8"
        )

    @classmethod
    def load(cls, directory: str | Path) -> "InMemoryVectorStore":
        directory = Path(directory)
        store = cls()
        store._vectors = np.load(directory / _VECTORS_FILE)
        store._chunks = json.loads((directory / _CHUNKS_FILE).read_text(encoding="utf-8"))
        return store


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
