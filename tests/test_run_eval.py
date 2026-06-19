from eval.run_eval import score_question


def test_retrieval_hit_when_expected_file_is_retrieved():
    score = score_question(
        retrieved_paths=["app/chunk.py", "app/other.py"],
        answer="Chunking lives in app/chunk.py.",
        refused=False,
        expected_files=["app/chunk.py"],
        expected_keywords=["chunk"],
    )
    assert score["retrieval_hit"] is True
    assert score["answer_correct"] is True


def test_retrieval_measures_topk_not_citations():
    # The expected file was retrieved even though the answer never names it;
    # retrieval hit must be True (retrieval quality is independent of the answer).
    score = score_question(
        retrieved_paths=["app/chunk.py"],
        answer="It is handled internally.",
        refused=False,
        expected_files=["app/chunk.py"],
        expected_keywords=["handled"],
    )
    assert score["retrieval_hit"] is True


def test_retrieval_miss_and_keyword_miss():
    score = score_question(
        retrieved_paths=["app/other.py"],
        answer="Something unrelated.",
        refused=False,
        expected_files=["app/chunk.py"],
        expected_keywords=["chunk"],
    )
    assert score["retrieval_hit"] is False
    assert score["answer_correct"] is False
    assert score["missing_keywords"] == ["chunk"]


def test_refusal_on_answerable_question_is_a_miss():
    score = score_question(
        retrieved_paths=["app/chunk.py"],
        answer="I don't find that in the code.",
        refused=True,
        expected_files=["app/chunk.py"],
        expected_keywords=["chunk"],
    )
    assert score["retrieval_hit"] is True  # it WAS retrieved
    assert score["answer_correct"] is False  # but the model refused
