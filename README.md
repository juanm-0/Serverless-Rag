# Serverless-Rag — Phase 0 (local RAG proof)

Point it at a code repository, then ask natural-language questions and get
answers grounded in the actual code, cited to exact files and line ranges.

This is Phase 0: a local CLI + eval harness, no AWS. See
[`docs/PROJECT.md`](docs/PROJECT.md) for the full plan and later phases.

## Setup

Requires Python 3.11+ and an Anthropic API key.

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1   | Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...   # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

First run downloads the `all-MiniLM-L6-v2` embedding model and (via
sentence-transformers) `torch` — a large one-time install.

## 60-second demo

```bash
rag ingest --path .                       # build the index from this repo
rag query "Where does chunking happen?"   # grounded, cited answer
python -m eval.run_eval                    # score the golden set
```

Set `ANTHROPIC_MODEL=claude-haiku-4-5` for cheaper iteration; the default is
`claude-opus-4-8`.

## How it works

- **Ingest:** walk + filter files → line-based chunks (path + line range) →
  local embeddings → `index/vectors.npy` + `index/chunks.json`.
- **Query:** embed the question → brute-force cosine top-k → grounded prompt →
  Claude returns `{answer, used_block_ids, refused}` → mapped to citations.
- **Eval:** golden Q/A in `eval/golden.yaml`, scored for retrieval hit-rate and
  answer correctness.

Embeddings, vector store, and LLM are each pluggable behind one Protocol
(`app/types.py`) — swapping a vendor touches no query/ingest logic.

## Current eval score

_Fill in after running `python -m eval.run_eval` (e.g. retrieval 6/6, answers 5/6)._
