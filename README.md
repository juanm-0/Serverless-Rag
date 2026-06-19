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

Golden set: 6 questions about this repo. Provider: Groq (`llama-3.3-70b-versatile`).

- **Retrieval hit-rate: 5/6 (83%)**
- **Answer correctness: 5/6 (83%)**

The two misses are honest eval signal, not bugs, and point at the next tuning levers:

1. *"How does ingestion decide which files to skip?"* — the right file **was** retrieved
   and the answer was correct, but it didn't contain the exact substring `node_modules`.
   This is the known limitation of deterministic keyword scoring (chosen over an
   LLM-as-judge for Phase 0; the latter is the obvious next step).
2. *"What is the grounding contract the LLM must return?"* — retrieval **miss**: the
   `docs/` (this repo's own design spec and implementation plan reproduce the code as
   prose) out-rank `app/generate.py` for a conceptual query. This is the classic
   pure-vector-search weakness on code-vs-docs, and motivates Phase 3's hybrid
   (vector + keyword) retrieval.

This is the number that moves as you tune chunk size, `k`, the prompt, the corpus,
and the scoring method.
