"""Retrieval: embed the question and return the top-k most similar chunks."""
from __future__ import annotations

from app.types import EmbeddingProvider, Hit, VectorStore


def retrieve(
    store: VectorStore,
    embedder: EmbeddingProvider,
    question: str,
    k: int = 8,
) -> list[Hit]:
    query_vector = embedder.embed([question])[0]
    return store.search(query_vector, k)
