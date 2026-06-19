"""Eval harness: run the golden questions through the RAG path and score.

  python -m eval.run_eval --index index --golden eval/golden.yaml

Scoring (deterministic, cheap):
  - retrieval hit-rate: did an expected file appear among the TOP-K RETRIEVED
    chunks? (measured against retrieval directly, independent of what the LLM
    chose to cite — this is the retrieval-quality number Phase 0 exists to move)
  - answer correctness: all expected keywords present (case-insensitive) in a
    non-refused answer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

DEFAULT_K = 8


def score_question(
    retrieved_paths: list[str],
    answer: str,
    refused: bool,
    expected_files: list[str],
    expected_keywords: list[str],
) -> dict:
    """Score one golden question.

    retrieved_paths: file paths of the top-k retrieved chunks (NOT just cited).
    """
    retrieval_hit = any(f in retrieved_paths for f in expected_files)

    answer_lower = answer.lower()
    keywords_present = all(kw.lower() in answer_lower for kw in expected_keywords)
    answer_correct = (not refused) and keywords_present

    missing = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
    return {
        "retrieval_hit": retrieval_hit,
        "answer_correct": answer_correct,
        "missing_keywords": missing,
    }


def _run(index_dir: str, golden_path: str, k: int = DEFAULT_K) -> int:
    from app.generate import generate_answer
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.llm import make_llm
    from app.providers.vectorstore import InMemoryVectorStore
    from app.retrieve import retrieve

    golden = yaml.safe_load(Path(golden_path).read_text(encoding="utf-8"))
    store = InMemoryVectorStore.load(index_dir)
    embedder = SentenceTransformerEmbeddings()
    llm = make_llm()

    hits = correct = 0
    for item in golden:
        retrieved = retrieve(store, embedder, item["question"], k)
        retrieved_paths = [h["chunk"]["path"] for h in retrieved]
        generated = generate_answer(llm, item["question"], retrieved)
        score = score_question(
            retrieved_paths,
            generated["answer"],
            generated["refused"],
            item["expected_files"],
            item["expected_keywords"],
        )
        hits += int(score["retrieval_hit"])
        correct += int(score["answer_correct"])
        flag = "HIT " if score["retrieval_hit"] else "miss"
        ans = "OK  " if score["answer_correct"] else "bad "
        print(f"[retrieval {flag}] [answer {ans}] {item['question']}")
        if not score["retrieval_hit"]:
            print(f"    expected {item['expected_files']}, retrieved {sorted(set(retrieved_paths))}")
        if not score["answer_correct"]:
            detail = "refused" if generated["refused"] else f"missing keywords {score['missing_keywords']}"
            print(f"    {detail}")

    n = len(golden)
    print()
    print(f"Retrieval hit-rate : {hits}/{n} = {hits / n:.0%}")
    print(f"Answer correctness : {correct}/{n} = {correct / n:.0%}")

    results_dir = Path("eval/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "latest.json").write_text(
        json.dumps(
            {"n": n, "retrieval_hits": hits, "answers_correct": correct},
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv  # auto-load .env so provider keys are picked up

    load_dotenv()
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--index", default="index")
    parser.add_argument("--golden", default="eval/golden.yaml")
    parser.add_argument("-k", type=int, default=DEFAULT_K)
    ns = parser.parse_args(argv)
    return _run(ns.index, ns.golden, ns.k)


if __name__ == "__main__":
    raise SystemExit(main())
