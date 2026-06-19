"""Brute-force in-memory vector store with cosine similarity.

Persists to two files that map cleanly to S3 objects in Phase 1:
  - vectors.npy : float32 matrix, one row per chunk
  - chunks.json : list of Chunk dicts, row-aligned with the matrix
"""
from __future__ import annotations

import json
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
