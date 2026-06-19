"""Eval harness: run the golden questions through the query path and score.

  python -m eval.run_eval --index index --golden eval/golden.yaml

Scoring (deterministic, cheap):
  - retrieval hit-rate: did an expected file appear among the citations?
  - answer correctness: all expected keywords present (case-insensitive) and
    not a refusal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from app.types import QueryResult


def score_question(
    result: QueryResult, expected_files: list[str], expected_keywords: list[str]
) -> dict:
    cited_paths = {c["path"] for c in result["citations"]}
    retrieval_hit = any(f in cited_paths for f in expected_files)

    answer_lower = result["answer"].lower()
    keywords_present = all(kw.lower() in answer_lower for kw in expected_keywords)
    answer_correct = (not result["refused"]) and keywords_present

    return {"retrieval_hit": retrieval_hit, "answer_correct": answer_correct}


def _run(index_dir: str, golden_path: str) -> int:
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.llm import AnthropicLLM
    from app.providers.vectorstore import InMemoryVectorStore
    from app.query import answer_query

    golden = yaml.safe_load(Path(golden_path).read_text(encoding="utf-8"))
    store = InMemoryVectorStore.load(index_dir)
    embedder = SentenceTransformerEmbeddings()
    llm = AnthropicLLM()

    rows = []
    hits = correct = 0
    for item in golden:
        result = answer_query(store, embedder, llm, item["question"], k=8)
        score = score_question(result, item["expected_files"], item["expected_keywords"])
        hits += int(score["retrieval_hit"])
        correct += int(score["answer_correct"])
        rows.append((item["question"], score))
        flag = "HIT " if score["retrieval_hit"] else "miss"
        ans = "OK  " if score["answer_correct"] else "bad "
        print(f"[retrieval {flag}] [answer {ans}] {item['question']}")

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
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--index", default="index")
    parser.add_argument("--golden", default="eval/golden.yaml")
    ns = parser.parse_args(argv)
    return _run(ns.index, ns.golden)


if __name__ == "__main__":
    raise SystemExit(main())
