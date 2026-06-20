"""Local embeddings via sentence-transformers.

The heavy model import is deferred to construction so importing this module
(e.g. in tests) does not pull in torch. Pass `model=` to inject a fake.
"""
from __future__ import annotations

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
