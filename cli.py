"""RAG CLI — cloud by default, `--local` for the offline dev fallback.

  rag ingest <git-url> [--local <path-or-url>]   default: POST /ingest | --local: build a local index
  rag query  "<question>" [--local] [-k N]        default: POST /query  | --local: query a local index

By default the CLI talks to your deployed endpoint (INVOKE_URL + API_KEY from .env);
no AWS credentials needed. `--local` runs the whole pipeline on your machine instead
(Phase-0 dev mode: local embeddings + on-disk index).
"""
from __future__ import annotations

import argparse
import sys

from app.chunk import DEFAULT_OVERLAP, DEFAULT_WINDOW
from app.cloud import cloud_post


def _looks_like_url(source: str) -> bool:
    return source.startswith(("http://", "https://", "git@"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="RAG over a codebase — cloud by default.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Index a repo via the deployed endpoint (or --local).")
    p_ingest.add_argument("source", help="A git URL (default cloud), or a local path with --local.")
    p_ingest.add_argument("--local", action="store_true", help="Build a local on-disk index instead of the cloud.")
    p_ingest.add_argument("--out", default="index", help="Local index dir, with --local (default: index).")
    p_ingest.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    p_ingest.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)

    p_query = sub.add_parser("query", help="Ask a question of the deployed endpoint (or --local).")
    p_query.add_argument("question", help="The natural-language question.")
    p_query.add_argument("--local", action="store_true", help="Query a local on-disk index instead of the cloud.")
    p_query.add_argument("--index", default="index", help="Local index dir, with --local (default: index).")
    p_query.add_argument("-k", type=int, default=8, help="Top-k chunks to retrieve.")

    return parser


def _print_query_result(result: dict) -> None:
    print(result.get("answer", ""))
    print()
    citations = result.get("citations") or []
    if citations:
        print("Citations:")
        for c in citations:
            print(f"  - {c['path']}:{c['start_line']}-{c['end_line']}")
    else:
        print("Citations: (none)")
    print()
    tokens = result.get("tokens") or {"input": 0, "output": 0}
    print(
        f"[latency={result.get('latency_ms', '?')}ms "
        f"tokens in/out={tokens.get('input', 0)}/{tokens.get('output', 0)} "
        f"refused={result.get('refused')}]"
    )


def _cmd_ingest(ns: argparse.Namespace) -> int:
    if ns.local:
        from app.ingest import build_index, resolve_source
        from app.providers.embeddings import SentenceTransformerEmbeddings
        from app.providers.vectorstore import InMemoryVectorStore

        if _looks_like_url(ns.source):
            root = resolve_source(repo_url=ns.source)
        else:
            root = resolve_source(path=ns.source)
        embedder = SentenceTransformerEmbeddings()
        store = InMemoryVectorStore()
        n = build_index(root, embedder, store, window=ns.window, overlap=ns.overlap)
        store.save(ns.out)
        print(f"Indexed {n} chunks from {root} -> {ns.out}/")
        return 0

    # cloud (default)
    if not _looks_like_url(ns.source):
        print("error: cloud ingest needs a git URL (the Lambda clones it). Use --local for a path.", file=sys.stderr)
        return 2
    status, body = cloud_post("/ingest", {"repo_url": ns.source})
    if status == 202:
        print(f"Ingest started for {ns.source} (202). Indexing runs in the cloud — watch CloudWatch logs.")
        return 0
    print(f"error: ingest failed (HTTP {status}): {body}", file=sys.stderr)
    return 1


def _cmd_query(ns: argparse.Namespace) -> int:
    if ns.local:
        from app.providers.embeddings import SentenceTransformerEmbeddings
        from app.providers.llm import make_llm
        from app.providers.vectorstore import InMemoryVectorStore
        from app.query import answer_query

        store = InMemoryVectorStore.load(ns.index)
        embedder = SentenceTransformerEmbeddings()
        llm = make_llm()
        result = answer_query(store, embedder, llm, ns.question, k=ns.k)
        _print_query_result(result)
        return 0

    # cloud (default)
    status, body = cloud_post("/query", {"question": ns.question, "k": ns.k})
    if status == 200:
        _print_query_result(body)
        return 0
    print(f"error: query failed (HTTP {status}): {body}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv  # auto-load .env so keys / INVOKE_URL / API_KEY are picked up

    load_dotenv()
    ns = build_parser().parse_args(argv)
    if ns.command == "ingest":
        return _cmd_ingest(ns)
    if ns.command == "query":
        return _cmd_query(ns)
    return 1


if __name__ == "__main__":
    sys.exit(main())
