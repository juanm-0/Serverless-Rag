from app.providers.vectorstore import InMemoryVectorStore


def _chunk(i: int):
    return {
        "id": f"f.py:{i}-{i}",
        "path": "f.py",
        "start_line": i,
        "end_line": i,
        "text": f"chunk {i}",
    }


def test_search_ranks_by_cosine_similarity():
    store = InMemoryVectorStore()
    # vec for chunk 0 points along x, chunk 1 along y
    store.add([_chunk(0), _chunk(1)], [[1.0, 0.0], [0.0, 1.0]])
    hits = store.search([0.9, 0.1], k=2)
    assert [h["chunk"]["id"] for h in hits] == ["f.py:0-0", "f.py:1-1"]
    assert hits[0]["score"] > hits[1]["score"]


def test_search_respects_k():
    store = InMemoryVectorStore()
    store.add([_chunk(0), _chunk(1), _chunk(2)], [[1, 0], [0.5, 0.5], [0, 1]])
    assert len(store.search([1.0, 0.0], k=2)) == 2


def test_search_on_empty_store_returns_empty():
    assert InMemoryVectorStore().search([1.0, 0.0], k=5) == []


def test_save_and_load_round_trip(tmp_path):
    store = InMemoryVectorStore()
    store.add([_chunk(0), _chunk(1)], [[1.0, 0.0], [0.0, 1.0]])
    store.save(tmp_path)

    loaded = InMemoryVectorStore.load(tmp_path)
    hits = loaded.search([1.0, 0.0], k=1)
    assert hits[0]["chunk"]["id"] == "f.py:0-0"
    assert hits[0]["chunk"]["text"] == "chunk 0"
