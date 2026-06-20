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
        self.batch_sizes = []

    def embed_content(self, **kwargs):
        self.last_kwargs = kwargs
        texts = kwargs["contents"]
        self.batch_sizes.append(len(texts))
        # one 2-d vector per input text
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


def test_embed_chunks_requests_at_gemini_batch_limit():
    # Gemini rejects >100 inputs per request; embed must split into batches.
    client = _FakeClient()
    emb = GeminiEmbeddings(client=client)
    vecs = emb.embed([f"t{i}" for i in range(250)])
    assert len(vecs) == 250  # all vectors returned, in order
    assert client.models.batch_sizes == [100, 100, 50]  # 3 batched calls
