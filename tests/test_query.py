from app.query import answer_query
from app.providers.vectorstore import InMemoryVectorStore


class _FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeLLM:
    last_usage = {"input": 4, "output": 6}

    def generate(self, system, user):
        return '{"answer": "A.", "used_blocks": [1], "refused": false}'


def test_answer_query_returns_full_result_shape():
    store = InMemoryVectorStore()
    store.add(
        [{"id": "f.py:1-1", "path": "f.py", "start_line": 1, "end_line": 1, "text": "code"}],
        [[1.0, 0.0]],
    )
    result = answer_query(store, _FakeEmbedder(), _FakeLLM(), "where?", k=3)
    assert result["answer"] == "A."
    assert result["refused"] is False
    assert result["citations"] == [{"path": "f.py", "start_line": 1, "end_line": 1}]
    assert result["tokens"] == {"input": 4, "output": 6}
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0
