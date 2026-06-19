# Phase 0 — Local RAG Proof — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design), pending implementation plan
**Source of truth:** [`docs/PROJECT.md`](../../PROJECT.md). This spec refines Phase 0 only; it does not
override PROJECT.md. Where they conflict, PROJECT.md wins.

---

## 1. Purpose & Scope

Prove the retrieval-augmented-generation (RAG) core entirely on a local machine, with **no AWS and no
FastAPI**. The deliverable is a CLI that:

1. Ingests a code repository (this project itself, or any public repo URL) into a local index.
2. Answers natural-language questions about it with answers **grounded** in retrieved code and
   **cited** to exact file paths + line ranges.
3. Refuses ("I don't find that in the code") when retrieved context is insufficient.
4. Produces a first **eval number** (retrieval hit-rate + answer correctness) from a golden question set.

**Exit criterion (from PROJECT.md):** cited answers from the terminal + a first eval score.

### In scope
- One-shot local ingestion of a single repo (local path or `git clone` of a public URL).
- Line-based chunking with file/line metadata.
- Local embeddings, brute-force in-memory cosine retrieval.
- Grounded, cited answer generation via the Anthropic Claude API.
- A CLI (`ingest`, `query`) and an eval harness over `golden.yaml`.
- Unit tests per provider + chunker; eval harness as the integration test.

### Out of scope for Phase 0 (deferred to later phases)
- FastAPI app, Lambda handlers, S3/DynamoDB, Terraform, CI, CloudWatch — **all Phase 1**.
- Tool-calling agent loop — **Phase 2**.
- OpenSearch / tree-sitter / containers / web UI — **Phase 3**.
- Anything on the PROJECT.md "out of scope" list (auth, multi-repo, fine-tuning, live re-indexing).

## 2. Provider Decisions (Phase 0)

These were the open choices in PROJECT.md; resolved for Phase 0 only. All remain pluggable.

| Concern       | Phase 0 choice                              | Notes |
|---------------|---------------------------------------------|-------|
| LLM           | **Anthropic Claude API** (`LLMProvider`)    | Exact model id pulled from the `claude-api` reference at build time. Needs `ANTHROPIC_API_KEY`. |
| Embeddings    | **Local sentence-transformers** (`all-MiniLM-L6-v2`) | Zero cost, offline, no key. Heavy install (torch). |
| Vector store  | **Brute-force in-memory** from local files  | `index/vectors.npy` + `index/chunks.json`. |
| Target repo   | **This project itself**                     | By ingest time, `app/` contains real Python to query. Any public URL also works. |

**Known Phase 1 tension (flagged, not solved here):** `torch` + `sentence-transformers` exceeds the
zipped-Lambda size limit (~250 MB). The query path in Phase 1 will need a hosted embedding provider or
a Lambda container image. The `EmbeddingProvider` interface exists precisely so this swap touches no
query/ingest logic.

## 3. Module Layout

A subset of the PROJECT.md repo layout — only what Phase 0 needs.

```
app/
  types.py            # Chunk, Hit TypedDicts + EmbeddingProvider/VectorStore/LLMProvider Protocols
  ingest.py           # resolve source (local path OR git clone), walk + filter files
  chunk.py            # line-based fixed-window chunking w/ overlap + path/line metadata
  retrieve.py         # embed query, top-k cosine over the store
  generate.py         # build grounded prompt, call LLM, parse structured JSON result
  providers/
    __init__.py
    embeddings.py     # SentenceTransformerEmbeddings (all-MiniLM-L6-v2)
    vectorstore.py    # InMemoryVectorStore w/ save()/load() to local files
    llm.py            # AnthropicLLM
cli.py                # `ingest` and `query` subcommands
eval/
  golden.yaml         # 5-10 Q/A + expected-file pairs about THIS repo
  run_eval.py         # scores retrieval hit-rate + answer correctness, prints summary
tests/                # unit tests per provider + chunker + generate JSON contract
pyproject.toml        # deps + console-script entrypoint
README.md             # setup + 60-second demo (updated each phase)
```

**Dependency rule (non-negotiable):** `ingest.py`, `chunk.py`, `retrieve.py`, `generate.py` depend
only on the Protocols in `types.py`. They never import a vendor SDK. Concrete vendors live solely in
`app/providers/` and are injected.

## 4. Interfaces

Authoritative copy lives in `app/types.py`, matching PROJECT.md exactly:

```python
from typing import Protocol, TypedDict

class Chunk(TypedDict):
    id: str            # stable id, e.g. f"{path}:{start_line}-{end_line}"
    path: str          # repo-relative file path
    start_line: int
    end_line: int
    text: str

class Hit(TypedDict):
    chunk: Chunk
    score: float

class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, query_vector: list[float], k: int) -> list[Hit]: ...

class LLMProvider(Protocol):
    def generate(self, system: str, user: str) -> str: ...
```

## 5. Key Micro-Decisions

### 5.1 Chunking — line-based fixed window
- Default window **60 lines**, overlap **15 lines** (both configurable via CLI flags / constants).
- Splitting on line boundaries makes `start_line`/`end_line` exact, so citations are free and precise.
- Each chunk carries `path` (repo-relative), `start_line`, `end_line` (1-indexed, inclusive), `text`,
  and a stable `id = f"{path}:{start_line}-{end_line}"`.
- Files shorter than one window produce a single chunk spanning the whole file.

### 5.2 File filtering (ingest)
Skip: `.git/`, `node_modules/`, `dist/`, `build/`, `target/`, `__pycache__/`, `.venv/`, virtualenvs;
binaries and non-text files (detected by extension allow-list + a null-byte sniff); lockfiles
(`package-lock.json`, `poetry.lock`, etc.); and any file larger than a size threshold (default 1 MB).
Index a conservative allow-list of source/text extensions (`.py`, `.js`, `.ts`, `.go`, `.java`, `.md`,
`.txt`, `.yaml`, `.toml`, etc.). The corpus is capped to stay fast and free.

### 5.3 On-disk index format
- `index/vectors.npy` — a `float32` matrix, one row per chunk (numpy `save`).
- `index/chunks.json` — a JSON list of `Chunk` dicts, row-aligned with the matrix.
- `InMemoryVectorStore.save(dir)` / `.load(dir)` handle both. In Phase 1 these two files become S3
  objects with **no format change** — the store implementation swaps, the format does not.

### 5.4 Grounding contract — structured JSON
- The prompt presents retrieved chunks as **numbered context blocks**, each labeled with its
  `id`/path/line-range.
- The model is instructed to answer **only** from those blocks and to return a single JSON object:

  ```json
  {"answer": "...", "used_block_ids": ["app/chunk.py:1-60", "..."], "refused": false}
  ```

- If the blocks do not contain the answer, it returns
  `{"answer": "I don't find that in the code.", "used_block_ids": [], "refused": true}`.
- `generate.py` parses this JSON, maps `used_block_ids` back to the corresponding `Hit`s, and returns a
  result object. This avoids brittle prose-regex citation parsing and makes the citation path directly
  unit-testable. Malformed JSON from the model is treated as a refusal-with-error (fail closed, logged).

### 5.5 Query result shape (parity with Phase 1 API)
`query()` returns the same shape the Phase 1 `POST /query` will return:

```json
{
  "answer": "string",
  "citations": [{"path": "app/chunk.py", "start_line": 1, "end_line": 60}],
  "refused": false,
  "latency_ms": 1234,
  "tokens": {"input": 0, "output": 0}
}
```

Building this shape now means Phase 1 wraps the same function with no reshaping.

## 6. Data Flow

**Ingest:** source → walk + filter → chunk → embed (local model, batched) → `InMemoryVectorStore.add`
→ `save()` to `index/`.

**Query:** `load()` index → embed question → top-k cosine → build grounded prompt → Claude → parse JSON
→ return result shape above. Observability: log latency, retrieved chunk ids, and token usage.

**Eval:** load `golden.yaml` → run the query path per question → score:
- **Retrieval hit-rate:** did an expected file appear among the top-k retrieved chunks?
- **Answer correctness:** keyword/substring match against expected answer (deterministic, cheap) for
  Phase 0; an LLM-as-judge variant may be added later. Refusals on answerable questions count as misses.
→ print a per-question table + aggregate numbers, and write results to `eval/results/`.

## 7. CLI

- `ingest [--path DIR | --repo-url URL] [--out index/] [--window 60] [--overlap 15]` — builds the index.
- `query "question" [--index index/] [-k 8]` — prints the answer, citations, latency, tokens.
- Wired as a console script in `pyproject.toml`.

## 8. Testing Strategy

TDD per the superpowers workflow — tests precede implementation:

- **chunk.py:** window/overlap line math, metadata correctness, short-file single-chunk, stable ids.
- **vectorstore.py:** cosine ranking order, top-k truncation, `save()`/`load()` round-trip equality.
- **embeddings.py:** shape/contract of `embed()` (model boundary faked so tests stay offline & fast).
- **llm.py:** request construction + response handling with the Anthropic client faked.
- **generate.py:** prompt construction, JSON-contract parsing, `used_block_ids` → citation mapping,
  refusal path, and malformed-JSON fail-closed behavior.
- **Integration:** `eval/run_eval.py` over `golden.yaml` is the end-to-end test and the headline metric.

## 9. AWS

**Phase 0 requires no AWS setup whatsoever.** The first manual AWS steps (Free Plan signup, $1 Budget
alarm, IAM, the Bedrock-vs-external decision, Terraform) belong to Phase 1 and will be delivered as an
explicit checklist before any `terraform apply`.

## 10. Success Criteria (Phase 0)

- `ingest` then `query` from the terminal yields a correct answer citing the right file(s).
- The eval harness prints a number for retrieval hit-rate + answer correctness that **moves** when chunk
  size, `k`, or the prompt is tuned.
- All unit tests pass; the run is fully local and free.
