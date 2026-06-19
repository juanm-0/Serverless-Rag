"""Query orchestration: retrieve -> generate -> timed parity result.

Returns the same shape the Phase 1 POST /query endpoint will return, so Phase 1
can wrap this function with no reshaping.
"""
from __future__ import annotations

import time

from app.generate import generate_answer
from app.retrieve import retrieve
from app.types import EmbeddingProvider, LLMProvider, QueryResult, VectorStore


def answer_query(
    store: VectorStore,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    question: str,
    k: int = 8,
) -> QueryResult:
    started = time.perf_counter()
    hits = retrieve(store, embedder, question, k)
    generated = generate_answer(llm, question, hits)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "answer": generated["answer"],
        "citations": generated["citations"],
        "refused": generated["refused"],
        "latency_ms": latency_ms,
        "tokens": generated["tokens"],
    }
