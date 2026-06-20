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


def test_build_user_prompt_numbers_blocks_and_includes_question():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    prompt = build_user_prompt("where is auth?", hits)
    assert "[1] (a.py lines 1-2)" in prompt
    assert "[2] (b.py lines 3-4)" in prompt
    assert "code A" in prompt
    assert "where is auth?" in prompt


def test_generate_answer_maps_block_numbers_to_citations():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    llm = _FakeLLM('{"answer": "In a.py.", "used_blocks": [1], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["answer"] == "In a.py."
    assert result["refused"] is False
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]
    assert result["tokens"] == {"input": 3, "output": 2}


def test_generate_answer_handles_string_block_numbers():
    # weak models sometimes return numbers as strings — coerce them.
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    llm = _FakeLLM('{"answer": "Both.", "used_blocks": ["1", "2"], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["citations"] == [
        {"path": "a.py", "start_line": 1, "end_line": 2},
        {"path": "b.py", "start_line": 3, "end_line": 4},
    ]


def test_generate_answer_handles_refusal():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "I don\'t find that in the code.", "used_blocks": [], "refused": true}')
    result = generate_answer(llm, "unrelated?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_fails_closed_on_bad_json():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM("not json at all")
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_ignores_out_of_range_and_junk_block_numbers():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "x", "used_blocks": [9, "foo", 1], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]


def test_generate_answer_dedupes_repeated_block_numbers():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "x", "used_blocks": [1, 1], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]


def test_generate_answer_fails_closed_when_used_blocks_is_not_a_list():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "x", "used_blocks": 5, "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_fails_closed_when_answer_is_not_a_string():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": {"nested": 1}, "used_blocks": [], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_fails_closed_on_top_level_json_array():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('["not", "an", "object"]')
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []
