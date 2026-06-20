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
