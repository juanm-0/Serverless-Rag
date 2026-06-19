import numpy as np

from app.providers.embeddings import SentenceTransformerEmbeddings


class _FakeModel:
    """Stand-in for a SentenceTransformer: .encode returns a numpy array."""

    def encode(self, texts):
        # one 2-d vector per text, deterministic from length
        return np.array([[float(len(t)), 1.0] for t in texts], dtype=np.float32)


def test_embed_returns_one_vector_per_text():
    emb = SentenceTransformerEmbeddings(model=_FakeModel())
    vecs = emb.embed(["a", "bbb"])
    assert len(vecs) == 2
    assert vecs[0] == [1.0, 1.0]
    assert vecs[1] == [3.0, 1.0]


def test_embed_returns_plain_python_floats():
    emb = SentenceTransformerEmbeddings(model=_FakeModel())
    vecs = emb.embed(["x"])
    assert isinstance(vecs, list)
    assert isinstance(vecs[0][0], float)
