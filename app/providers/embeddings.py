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
