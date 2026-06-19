from app.types import Chunk, Hit, Citation, Tokens, QueryResult


def test_chunk_and_hit_are_constructible_dicts():
    chunk: Chunk = {
        "id": "app/chunk.py:1-60",
        "path": "app/chunk.py",
        "start_line": 1,
        "end_line": 60,
        "text": "def chunk_file(): ...",
    }
    hit: Hit = {"chunk": chunk, "score": 0.87}
    assert hit["chunk"]["path"] == "app/chunk.py"
    assert hit["score"] == 0.87


def test_query_result_shape():
    result: QueryResult = {
        "answer": "It happens in chunk.py.",
        "citations": [Citation(path="app/chunk.py", start_line=1, end_line=60)],
        "refused": False,
        "latency_ms": 12,
        "tokens": Tokens(input=10, output=5),
    }
    assert result["citations"][0]["path"] == "app/chunk.py"
    assert result["tokens"]["output"] == 5
