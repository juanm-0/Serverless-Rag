Here's the product, framed around what you're actually building and why, not the cloud plumbing.
The goal in one sentence
A service you point at a public code repository that indexes the code, then answers natural‑language questions about it ("where does auth happen?", "what does retryWithBackoff do?", "how are payments processed?") with answers grounded in the actual code and citing the specific files they came from. It's a focused, self‑hosted slice of what Cursor or Claude Code do when they "understand your codebase", and building it teaches you exactly how that machinery works from the inside.
Scope
In scope (what it does):

Pull in a public repo and turn its files into a searchable knowledge base.
Take a question and find the most relevant pieces of code.
Generate an answer that uses only those pieces, and cites them.
Measure its own answer quality with a repeatable test.

Deliberately out of scope (so it doesn't sprawl):

No live re‑indexing on every commit, ingest is a one‑shot you re‑run when you want.
No polished UI; the API is the product (a tiny CLI or HTML page is plenty).
No auth, users, or multi‑repo/multi‑tenant.
No model fine‑tuning, it's pure retrieval‑augmented generation.
No giant repos, you cap the corpus to keep it fast and free.

Keeping that "out" list explicit is half the discipline; it's what stops a weekend project from becoming a quarter.
Functional requirements (what it must do)

Ingest — given a repo URL, clone it, walk the files, and filter to the ones worth indexing (skip .git, node_modules, build output, binaries).
Chunk — split each file into retrievable pieces, carrying file path + line range as metadata so answers can cite them. (MVP: fixed‑size chunks with overlap; later: function/class‑aware splitting.)
Embed — convert each chunk into a vector with an embedding model.
Store — persist the vectors plus chunk text and metadata so they can be loaded for search.
Retrieve — embed the question, return the top‑k most similar chunks.
Generate (grounded) — prompt the LLM with the question + retrieved chunks, instructing it to answer only from that context and to say "I don't find that in the code" when the context is insufficient. This anti‑hallucination rule is the heart of the quality bar.
Cite — return which files/line ranges the answer used, so a human can verify it.
Evaluate — a set of known question/answer pairs about the repo, run automatically, scored for retrieval hit‑rate and answer correctness.
Expose — at minimum POST /ingest and POST /query.
Observe — log each request's latency, retrieved chunks, and token usage.

The non‑negotiables that make it good rather than a toy: grounded, cited, and measured. Anyone can wire an LLM to a vector store; the citations and the eval harness are what signal real engineering judgment.
Tech stack
Organized by layer; the bolded pieces are the ones that define the tool.

Language: Python, it has the richest RAG ecosystem and matches the AI roles you're targeting.
Ingestion: git (clone) + pathlib (walk/filter). Chunking via a simple recursive text splitter to start; optionally tree-sitter later for syntax‑aware, function‑level chunks.
Embeddings (pluggable): a sentence‑transformer model run locally during ingest, or a hosted embedding model. Treat this as a swappable component behind one function.
Vector store + retrieval: for the MVP, store vectors as a file and do brute‑force cosine similarity in memory. Simple, free, and it forces you to understand what a vector search actually is before you reach for a managed one.
Metadata: a key‑value store (or just bundled alongside the vectors for the MVP).
LLM / generation (pluggable): a chat model behind a single generate(question, context) function, with a prompt template that enforces grounding + citations.
API: write it as a small FastAPI app so you can run it locally, then deploy the same app serverless. Local‑dev parity is a big quality‑of‑life win.
Eval harness: a Python script (or pytest) reading a golden‑question file (YAML/JSON), running the query flow, and scoring the results.
Runtime + delivery: serverless functions behind a gateway, provisioned with Terraform, deployed via GitHub Actions, logged to CloudWatch. (The cloud layer you already have the diagram for.)

The design principle worth internalizing: the embedding model, the LLM, and the vector store are all pluggable. Hide each behind one interface. That modularity is both good engineering and a clean thing to talk about in an interview ("I kept retrieval swappable so I could move from brute‑force to OpenSearch without touching the query logic").
How it works, end to end

Ingest path: repo URL → clone → filter files → chunk (+ file/line metadata) → embed → store vectors + metadata.
Query path: question → embed → retrieve top‑k → build a grounded, cite‑instructed prompt → LLM → answer + citations → return.
Eval path: golden questions → run the query path → compare against expected → score → record.

Build phases (so you always know what "done" looks like)

Phase 0 — local proof (fastest feedback): ingest a small repo entirely on your machine, embed, brute‑force retrieve, generate one cited answer. No cloud yet. This proves the RAG core in isolation, the most important thing to get right.
Phase 1 — serverless MVP: wrap ingest + query behind the API on AWS, with the vectors/metadata stored in the cloud, Terraform + CI + observability. This is the deployable product and the résumé artifact.
Phase 2 — make it an agent: turn retrieval into a tool the LLM calls, and add one or two more (read_file, list_files, grep), then let the model decide which to call to answer a question. This is the step that converts a RAG pipeline into a genuine tool‑calling agent, exactly the conversational‑agent capability that was your soft spot for the Owner/Mediafly‑type roles.
Phase 3 — optional scale‑ups: swap brute‑force for OpenSearch (hybrid search), move ingest to a container, add a small web UI.

How you know it's working

You can ask a real question about the indexed repo and get a correct answer that cites the right files.
The eval harness produces a number (retrieval hit‑rate, answer correctness on the golden set), and you can watch it improve as you tune chunk size, k, and the prompt. Being able to say "I moved faithfulness from 78% to 94% by doing X" is the single most credible thing you'll get out of this.
It deploys with one command and tears down cleanly.