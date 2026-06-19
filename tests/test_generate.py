from app.generate import build_user_prompt, generate_answer


def _hit(cid, path, s, e, text, score=0.9):
    return {
        "chunk": {"id": cid, "path": path, "start_line": s, "end_line": e, "text": text},
        "score": score,
    }


class _FakeLLM:
    def __init__(self, raw):
        self._raw = raw
        self.last_usage = {"input": 3, "output": 2}

    def generate(self, system, user):
        self.captured = (system, user)
        return self._raw


def test_build_user_prompt_includes_numbered_blocks_and_question():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    prompt = build_user_prompt("where is auth?", hits)
    assert "a.py:1-2" in prompt
    assert "code A" in prompt
    assert "where is auth?" in prompt


def test_generate_answer_maps_used_ids_to_citations():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    llm = _FakeLLM('{"answer": "In a.py.", "used_block_ids": ["a.py:1-2"], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["answer"] == "In a.py."
    assert result["refused"] is False
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]
    assert result["tokens"] == {"input": 3, "output": 2}


def test_generate_answer_handles_refusal():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "I don\'t find that in the code.", "used_block_ids": [], "refused": true}')
    result = generate_answer(llm, "unrelated?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_fails_closed_on_bad_json():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM("not json at all")
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_ignores_unknown_block_ids():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "x", "used_block_ids": ["ghost:9-9", "a.py:1-2"], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]
