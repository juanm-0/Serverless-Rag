"""Phase 0 CLI: ingest a repo, then ask cited questions about it.

  rag ingest --path .            # build the index from a local dir
  rag ingest --repo-url <URL>    # build the index from a cloned public repo
  rag query "where does X?"      # answer a question with citations
"""
from __future__ import annotations

import argparse
import json
import sys

from app.chunk import DEFAULT_OVERLAP, DEFAULT_WINDOW


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="Local RAG over a codebase.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Build the index from a repo.")
    src = p_ingest.add_mutually_exclusive_group(required=True)
    src.add_argument("--path", help="Local directory to index.")
    src.add_argument("--repo-url", dest="repo_url", help="Public git URL to clone and index.")
    p_ingest.add_argument("--out", default="index", help="Output index directory (default: index).")
    p_ingest.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    p_ingest.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)

    p_query = sub.add_parser("query", help="Ask a question about the indexed repo.")
    p_query.add_argument("question", help="The natural-language question.")
    p_query.add_argument("--index", default="index", help="Index directory (default: index).")
    p_query.add_argument("-k", type=int, default=8, help="Top-k chunks to retrieve.")

    return parser


def _cmd_ingest(ns: argparse.Namespace) -> int:
    from app.ingest import build_index, resolve_source
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.vectorstore import InMemoryVectorStore

    root = resolve_source(path=ns.path, repo_url=ns.repo_url)
    embedder = SentenceTransformerEmbeddings()
    store = InMemoryVectorStore()
    n = build_index(root, embedder, store, window=ns.window, overlap=ns.overlap)
    store.save(ns.out)
    print(f"Indexed {n} chunks from {root} -> {ns.out}/")
    return 0


def _cmd_query(ns: argparse.Namespace) -> int:
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.llm import make_llm
    from app.providers.vectorstore import InMemoryVectorStore
    from app.query import answer_query

    store = InMemoryVectorStore.load(ns.index)
    embedder = SentenceTransformerEmbeddings()
    llm = make_llm()
    result = answer_query(store, embedder, llm, ns.question, k=ns.k)

    print(result["answer"])
    print()
    if result["citations"]:
        print("Citations:")
        for c in result["citations"]:
            print(f"  - {c['path']}:{c['start_line']}-{c['end_line']}")
    else:
        print("Citations: (none)")
    print()
    print(
        f"[latency={result['latency_ms']}ms "
        f"tokens in/out={result['tokens']['input']}/{result['tokens']['output']} "
        f"refused={result['refused']}]"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv  # auto-load .env so provider keys are picked up

    load_dotenv()
    ns = build_parser().parse_args(argv)
    if ns.command == "ingest":
        return _cmd_ingest(ns)
    if ns.command == "query":
        return _cmd_query(ns)
    return 1


if __name__ == "__main__":
    sys.exit(main())
