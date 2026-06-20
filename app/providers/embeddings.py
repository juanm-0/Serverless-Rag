"""Local embeddings via sentence-transformers.

The heavy model import is deferred to construction so importing this module
(e.g. in tests) does not pull in torch. Pass `model=` to inject a fake.
"""
from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"


class SentenceTransformerEmbeddings:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, model: Any | None = None) -> None:
        if model is not None:
            self._model = model
        else:
            from sentence_transformers import SentenceTransformer  # lazy, heavy import

            self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts)
        return np.asarray(vectors, dtype=np.float32).tolist()


DEFAULT_GEMINI_EMBED_MODEL = "gemini-embedding-001"
_GEMINI_MAX_BATCH = 100  # Gemini embed_content allows at most 100 inputs per request


def _is_rate_limit(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "rate limit" in text


class GeminiEmbeddings:
    """Hosted embeddings via Google Gemini (google-genai).

    Reads GEMINI_API_KEY (or GOOGLE_API_KEY). Pass `client=` to inject a fake.
    Batches at <=100 inputs (the API cap) and retries on 429 with back-off so a
    large corpus survives the free tier's tokens-per-minute limit. Override the
    batch size with GEMINI_EMBED_BATCH (smaller = friendlier to the free tier).
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        max_retries: int = 6,
    ) -> None:
        self.model = model or os.environ.get("GEMINI_EMBED_MODEL", DEFAULT_GEMINI_EMBED_MODEL)
        env_batch = os.environ.get("GEMINI_EMBED_BATCH")
        chosen = batch_size or (int(env_batch) if env_batch else _GEMINI_MAX_BATCH)
        self.batch_size = max(1, min(chosen, _GEMINI_MAX_BATCH))
        self.max_retries = max_retries
        if client is not None:
            self._client = client
        else:
            from google import genai  # lazy import; reads GEMINI_API_KEY / GOOGLE_API_KEY

            self._client = genai.Client()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[i : i + self.batch_size]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        for attempt in range(self.max_retries):
            try:
                response = self._client.models.embed_content(model=self.model, contents=batch)
                return [[float(x) for x in e.values] for e in response.embeddings]
            except Exception as exc:  # noqa: BLE001 - retry only on rate limits
                if _is_rate_limit(exc) and attempt < self.max_retries - 1:
                    time.sleep(min(15 * (attempt + 1), 60))  # wait for the per-minute window
                    continue
                raise
        return []  # unreachable: loop either returns or raises
