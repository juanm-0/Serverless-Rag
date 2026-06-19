from app.retrieve import retrieve
from app.providers.vectorstore import InMemoryVectorStore


class _FakeEmbedder:
    def embed(self, texts):
        # "x" -> points along axis 0, anything else -> axis 1
        return [[1.0, 0.0] if t == "x" else [0.0, 1.0] for t in texts]


def _chunk(cid, vec_axis):
    return {"id": cid, "path": "f.py", "start_line": 1, "end_line": 1, "text": cid}


def test_retrieve_embeds_query_and_returns_top_k():
    store = InMemoryVectorStore()
    store.add(
        [_chunk("along-x", 0), _chunk("along-y", 1)],
        [[1.0, 0.0], [0.0, 1.0]],
    )
    hits = retrieve(store, _FakeEmbedder(), "x", k=1)
    assert len(hits) == 1
    assert hits[0]["chunk"]["id"] == "along-x"
