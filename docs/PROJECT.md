# PROJECT.md — Chat With a Codebase

A self-hosted service you point at a public code repository. It indexes the code,
then answers natural-language questions about it ("where does auth happen?",
"what does `retryWithBackoff` do?") with answers that are **grounded in the actual
code and cite the specific files and line ranges they came from**.

This is a focused, transparent slice of what tools like Cursor or Claude Code do
when they "understand a codebase." The point is to build that machinery from the
inside, on free-tier AWS, provisioned as code, with a real evaluation harness.

---

## How to use this file (for the coding agent)

- This is the **source of truth**. When in doubt, follow this document.
- **Build toward Phase 1 first.** Do not start Phase 2/3 work until Phase 1 is green.
- **Respect the "out of scope" list.** If a change would add something on that list,
  stop and ask before doing it.
- **Keep the three providers pluggable** (embeddings, LLM, vector store). Never call
  a vendor SDK directly from the query/ingest logic. Go through the interfaces below.
- **Three non-negotiables for any answer path:** grounded, cited, measured.
- Prefer small, legible, well-tested code over cleverness. A tidy 300-line repo that
  deploys cleanly beats an ambitious half-finished one.

---

## Goal

Given a public repo URL, produce a service that:

1. Indexes the repo into a searchable knowledge base.
2. Answers questions using only retrieved code, with citations.
3. Says "I don't find that in the code" when the context is insufficient.
4. Measures its own answer quality with a repeatable evaluation.

---

## Scope

### In scope
- One-shot ingestion of a single public repo (re-run manually to refresh).
- Retrieval over the indexed code.
- Grounded, cited answer generation.
- An evaluation harness with a golden question set.
- A minimal HTTP API (`POST /ingest`, `POST /query`).
- Basic observability (latency, retrieved chunks, token usage).

### Out of scope (do not build these without explicit approval)
- Live/continuous re-indexing on every commit.
- A polished UI (a tiny CLI or single HTML page is the most that's allowed).
- Auth, user accounts, multi-repo or multi-tenant support.
- Model fine-tuning (this is pure retrieval-augmented generation).
- Very large repos (cap the corpus to stay fast and within free tier).

Keeping this list honest is half the discipline.

---

## Architecture (three paths)

**Ingest path**
repo URL -> clone -> filter files -> chunk (+ file/line metadata) -> embed -> store vectors + metadata

**Query path**
question -> embed -> retrieve top-k -> build grounded, cite-instructed prompt -> LLM -> answer + citations

**Eval path**
golden questions -> run the query path -> compare to expected -> score (hit-rate, correctness) -> record

The cloud topology (S3, Lambda, API Gateway, DynamoDB, Bedrock, CloudWatch, IAM,
Terraform, GitHub Actions) is documented separately in the architecture diagram.
This file is about the tool itself.

---

## Tech stack

- **Language:** Python.
- **Ingestion:** `git` to clone, `pathlib` to walk/filter. Skip `.git`, `node_modules`,
  build output, binaries, lockfiles, anything over a size threshold.
- **Chunking:** MVP = recursive fixed-size chunks with overlap, carrying `path` and
  `start_line`/`end_line`. Later (Phase 3): `tree-sitter` for function/class-aware chunks.
- **Embeddings (PLUGGABLE):** a sentence-transformer run locally during ingest, or a
  hosted embedding model. Behind `EmbeddingProvider`.
- **Vector store + retrieval (PLUGGABLE):** MVP = store vectors as a file (S3) and do
  **brute-force cosine similarity in memory** inside the query function. No running
  database. Behind `VectorStore`. (Phase 3: swap to OpenSearch / pgvector.)
- **Metadata:** DynamoDB (chunk metadata + eval results), or bundled with the vectors
  for the local Phase 0 proof.
- **LLM / generation (PLUGGABLE):** a chat model behind `LLMProvider`, with a prompt
  template that enforces grounding + citations.
- **API:** **FastAPI** app, runnable locally and deployable serverless (local-dev parity).
- **Eval harness:** Python + `pytest`, reading a golden-question YAML/JSON file.
- **Infra/delivery:** Terraform (IaC), GitHub Actions (CI: run evals + deploy),
  CloudWatch (logs/metrics, 30-day log retention set explicitly).

The design principle: the embedding model, the LLM, and the vector store are all
swappable behind one interface each. This is both good engineering and a clean thing
to be able to explain.

---

## Pluggable interfaces (do not bypass these)

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
    score: float       # similarity score

class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text. Used for both chunks and queries."""

class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, query_vector: list[float], k: int) -> list[Hit]: ...

class LLMProvider(Protocol):
    def generate(self, system: str, user: str) -> str:
        """Single-turn generation. Phase 2 adds a tool-calling variant."""
```

The query and ingest logic depend only on these protocols, never on a concrete vendor.

---

## Functional requirements

1. **Ingest** — clone a repo by URL, walk and filter files.
2. **Chunk** — split files into retrievable pieces with `path` + line range metadata.
3. **Embed** — turn chunks into vectors via `EmbeddingProvider`.
4. **Store** — persist vectors + chunk text + metadata via `VectorStore`.
5. **Retrieve** — embed the question, return top-k chunks.
6. **Generate (grounded)** — prompt the LLM with question + retrieved chunks; instruct
   it to answer only from context and to say "I don't find that in the code" otherwise.
7. **Cite** — return the file paths and line ranges the answer used.
8. **Evaluate** — run golden Q/A pairs, score retrieval hit-rate and answer correctness.
9. **Expose** — `POST /ingest {repo_url}` and `POST /query {question}` returning
   `{answer, citations[], latency_ms, tokens}`.
10. **Observe** — log per-request latency, retrieved chunk ids, and token usage.

### Non-negotiables
- **Grounded:** the answer uses only retrieved context. No outside knowledge.
- **Cited:** every answer returns the files/line ranges it relied on.
- **Measured:** the eval harness produces a number that moves when you tune the system.

---

## Suggested repo layout

```
.
├── PROJECT.md
├── README.md
├── pyproject.toml            # or requirements.txt
├── app/
│   ├── api.py                # FastAPI app: /ingest, /query
│   ├── ingest.py             # clone, filter, chunk
│   ├── chunk.py              # chunking logic + metadata
│   ├── retrieve.py           # embed query, top-k search
│   ├── generate.py           # grounded prompt + citation parsing
│   └── providers/
│       ├── embeddings.py     # EmbeddingProvider implementations
│       ├── vectorstore.py    # VectorStore implementations (brute-force MVP)
│       └── llm.py            # LLMProvider implementations
├── eval/
│   ├── golden.yaml           # question -> expected answer / expected files
│   └── run_eval.py           # scores hit-rate + correctness, writes results
├── infra/
│   └── *.tf                  # Terraform for the AWS resources
├── handlers/
│   ├── ingest_handler.py     # Lambda entrypoint -> app.ingest
│   └── query_handler.py      # Lambda entrypoint -> app.retrieve + generate
├── .github/workflows/
│   └── ci.yml                # run evals, then deploy
└── tests/
```

---

## Build phases

### Phase 0 — local proof (do this first)
Prove the RAG core with no cloud at all.

- [ ] Clone a small target repo locally.
- [ ] Walk + filter files; chunk with path/line metadata.
- [ ] Implement `EmbeddingProvider` (local model) and embed all chunks.
- [ ] Implement a brute-force in-memory `VectorStore` (cosine similarity).
- [ ] Implement `LLMProvider` and the grounded, cite-instructed prompt.
- [ ] Ask 3-5 real questions from the CLI and get correct, cited answers.
- [ ] Write `eval/golden.yaml` (5-10 Q/A pairs) and a first `run_eval.py`.

Exit criterion: cited answers from the terminal + a first eval score.

### Phase 1 — serverless MVP (the resume artifact)
Same core, now deployed and provisioned as code.

- [ ] Wrap ingest + query in the FastAPI app; run it locally end to end.
- [ ] Move vectors/metadata to S3 + DynamoDB behind the same interfaces.
- [ ] Write Lambda handlers that call into the app.
- [ ] Terraform: S3, DynamoDB, two Lambdas, API Gateway, IAM roles, CloudWatch.
- [ ] Set CloudWatch log retention to 30 days. Add a $1 AWS Budget alarm.
- [ ] GitHub Actions: run evals on push, deploy on main.
- [ ] README with setup, a 60-second demo, and the current eval score.

Exit criterion: `POST /query` returns a grounded, cited answer from AWS, deploys via
CI, and `terraform destroy` tears it all down cleanly.

### Phase 2 — make it an agent
Turn retrieval into a tool the model chooses to call.

- [ ] Add a tool-calling variant to `LLMProvider`.
- [ ] Expose `search_code` (retrieval) plus `read_file`, `list_files`, `grep` as tools.
- [ ] Let the model decide which tools to call to answer a question (agent loop).
- [ ] Extend the eval set with multi-step questions; confirm scores hold or improve.

This is the step that turns a RAG pipeline into a genuine tool-calling agent.

### Phase 3 — optional scale-ups

**Retrieval & answer quality** (motivated by the Phase 0 eval misses — pure-vector
retrieval lets prose docs out-rank code on conceptual queries, and substring scoring
under-counts correct answers):
- [ ] **Hybrid retrieval** — combine dense vector similarity with sparse keyword/BM25
      ranking so code files surface for conceptual natural-language queries (the Q5 miss).
      OpenSearch gives both in one store; for the brute-force path, fuse cosine with a
      lexical score (e.g. reciprocal-rank fusion).
- [ ] **Corpus weighting** — down-weight or exclude `docs/` (and other prose) when the
      question is about code, so code files win for code questions.
- [ ] **Code-aware embeddings** — swap general-purpose `all-MiniLM-L6-v2` for an
      embedding model trained on source code.
- [ ] **Tune chunking & `k`** — sweep window/overlap and top-`k`; pairs naturally with
      `tree-sitter` symbol-aware chunks below.
- [ ] **LLM-as-judge eval scoring** — replace brittle substring keyword matching with a
      cheap LLM grader (kept behind a flag alongside the deterministic scorer), so the
      correctness metric reflects semantic correctness, not exact-token echoing (the Q4
      false-negative).

**Private repository support** (index repos you have credentials for, not just public ones):
- [ ] **Authenticated clone** — accept a git credential (PAT / SSH deploy key / GitHub App
      token) so the ingest worker can `git clone` private repos. The credential never lands
      in the repo URL on disk: store it as an SSM `SecureString`, inject it at clone time
      (e.g. `x-access-token:<PAT>@` for HTTPS, or an in-memory `GIT_SSH_COMMAND` key), and
      scrub it from logs.
- [ ] **Per-caller credentials** — since this is bring-your-own-keys, let each deployer
      supply their own git token via SSM (one parameter per source/owner), keeping one
      user's private-repo access isolated from another's.
- [ ] **Least-privilege & expiry** — prefer short-lived/fine-grained tokens (GitHub App
      installation tokens, read-only deploy keys) scoped to just the repos being indexed.

**Local / non-git sources** (index a project that was never version-controlled — no upstream
to clone from):
- [ ] **Directory upload** — let a caller ingest a plain local folder instead of a git URL.
      The CLI packs the directory (tar/zip, honoring the same skip rules as the walker —
      `.git`, `node_modules`, build output, binaries, size cap) and uploads it to a scratch
      S3 prefix; the cloud ingest worker unpacks and indexes it. (Today's `--local` path
      chunks on the caller's machine; this brings non-git folders to the *cloud* pipeline.)
- [ ] **Source abstraction** — generalize `resolve_source` so ingest accepts `git-url`,
      `local-path`, or `uploaded-archive` behind one interface, instead of assuming a
      clonable URL.
- [ ] **Provenance metadata** — record the source kind/identifier on each chunk (no commit
      SHA exists for an uncontrolled folder), so citations and re-index still make sense.
- [ ] Swap brute-force for OpenSearch (the hybrid vector + keyword store above).
- [ ] `tree-sitter` syntax-aware chunking (function/class-aware blocks).
- [ ] Containerize the ingest worker (ECS Fargate) — Phase 1 already runs ingest as a
      container-image Lambda; Fargate is the next step for longer/larger ingests.
- [ ] A minimal web UI.

---

## Success criteria

- You can ask a real question about the indexed repo and get a **correct answer that
  cites the right files**.
- The eval harness produces a **number** (retrieval hit-rate + answer correctness) that
  **improves as you tune** chunk size, k, and the prompt. Being able to say
  "I moved faithfulness from 78% to 94% by doing X" is the headline outcome.
- It deploys with one command and tears down cleanly, with no surprise cost.

---

## Conventions and guardrails

- **Cost:** lean on always-free services (Lambda, S3, DynamoDB). No always-on instances
  in Phase 1. Free Plan at signup, $1 Budget alarm, 30-day log retention,
  `terraform destroy` when idle.
- **Grounding prompt:** always instruct the model to answer only from provided context
  and to refuse ("I don't find that in the code") when context is insufficient.
- **Citations:** return structured citations (path + line range), not just prose.
- **Tests:** every provider and the chunker get unit tests; the eval harness is the
  integration test.
- **Keep providers swappable:** new vendor = new class implementing the protocol,
  zero changes to query/ingest logic.