"""Core data shapes and the three pluggable provider Protocols.

This module is the contract. ingest/chunk/retrieve/generate depend only on
the Protocols defined here — never on a concrete vendor SDK.
"""
from __future__ import annotations

from typing import Protocol, TypedDict


class Chunk(TypedDict):
    id: str          # stable id, e.g. f"{path}:{start_line}-{end_line}"
    path: str        # repo-relative file path
    start_line: int  # 1-indexed, inclusive
    end_line: int    # 1-indexed, inclusive
    text: str


class Hit(TypedDict):
    chunk: Chunk
    score: float     # cosine similarity


class Citation(TypedDict):
    path: str
    start_line: int
    end_line: int


class Tokens(TypedDict):
    input: int
    output: int


class QueryResult(TypedDict):
    answer: str
    citations: list[Citation]
    refused: bool
    latency_ms: int
    tokens: Tokens


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text. Used for chunks and queries."""
        ...


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, query_vector: list[float], k: int) -> list[Hit]: ...


class LLMProvider(Protocol):
    def generate(self, system: str, user: str) -> str:
        """Single-turn generation. Returns the model's raw text response."""
        ...
