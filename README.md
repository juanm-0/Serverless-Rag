# Serverless-Rag — Phase 0 (local RAG proof)

Point it at a code repository, then ask natural-language questions and get
answers grounded in the actual code, cited to exact files and line ranges.

This is Phase 0: a local CLI + eval harness, no AWS. See
[`docs/PROJECT.md`](docs/PROJECT.md) for the full plan and later phases.

## Setup

Requires Python 3.11+ and one LLM provider key (the LLM is pluggable — pick any).

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1   | Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
```

First run downloads the `all-MiniLM-L6-v2` embedding model and (via
sentence-transformers) `torch` — a large one-time install. Embeddings run
locally; only answer-generation calls an LLM.

### Choose an LLM provider

Select with `LLM_PROVIDER` (default `groq`). Each provider reads its own key and
has an optional model override:

| `LLM_PROVIDER` | Free? | API key env var | Get a key | Default model (`*_MODEL` override) |
|---|---|---|---|---|
| `groq` (default) | yes | `GROQ_API_KEY` | console.groq.com → API Keys | `llama-3.3-70b-versatile` |
| `gemini` | yes | `GEMINI_API_KEY` | aistudio.google.com → Get API key | `gemini-2.0-flash` |
| `anthropic` | paid | `ANTHROPIC_API_KEY` | console.anthropic.com | `claude-opus-4-8` |

```bash
# Example: free Groq (Bash)
export LLM_PROVIDER=groq
export GROQ_API_KEY=gsk_...
```

## 60-second demo

```bash
.venv/Scripts/python.exe -m cli ingest --path .                    # build the index
.venv/Scripts/python.exe -m cli query "Where does chunking happen?" # grounded, cited answer
.venv/Scripts/python.exe -m eval.run_eval                           # score the golden set
```

(After `pip install`, the `rag` console script is also available, e.g.
`rag ingest --path .`. On Windows, `python` may resolve to a broken Store stub —
use the venv path `.venv/Scripts/python.exe` as shown.)

## How it works

- **Ingest:** walk + filter files → line-based chunks (path + line range) →
  local embeddings → `index/vectors.npy` + `index/chunks.json`.
- **Query:** embed the question → brute-force cosine top-k → grounded prompt →
  the LLM returns `{answer, used_block_ids, refused}` → mapped to citations.
- **Eval:** golden Q/A in `eval/golden.yaml`, scored for retrieval hit-rate and
  answer correctness.

Embeddings, vector store, and LLM are each pluggable behind one Protocol
(`app/types.py`) — swapping a vendor touches no query/ingest logic.

## Current eval score

_Fill in after running `python -m eval.run_eval` (e.g. retrieval 6/6, answers 5/6)._
