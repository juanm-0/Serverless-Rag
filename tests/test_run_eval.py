from eval.run_eval import score_question


def _result(answer, citations, refused=False):
    return {
        "answer": answer,
        "citations": citations,
        "refused": refused,
        "latency_ms": 1,
        "tokens": {"input": 0, "output": 0},
    }


def test_retrieval_hit_when_expected_file_is_cited():
    result = _result("Chunking lives in app/chunk.py.", [{"path": "app/chunk.py", "start_line": 1, "end_line": 60}])
    score = score_question(
        result,
        expected_files=["app/chunk.py"],
        expected_keywords=["chunk"],
    )
    assert score["retrieval_hit"] is True
    assert score["answer_correct"] is True


def test_retrieval_miss_and_keyword_miss():
    result = _result("Something unrelated.", [{"path": "app/other.py", "start_line": 1, "end_line": 2}])
    score = score_question(result, expected_files=["app/chunk.py"], expected_keywords=["chunk"])
    assert score["retrieval_hit"] is False
    assert score["answer_correct"] is False


def test_refusal_on_answerable_question_is_a_miss():
    result = _result("I don't find that in the code.", [], refused=True)
    score = score_question(result, expected_files=["app/chunk.py"], expected_keywords=["chunk"])
    assert score["answer_correct"] is False
