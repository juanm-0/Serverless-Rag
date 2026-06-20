# AWS Concepts & Tech Stack — Review Guide

A learning reference for the **Phase 1 (serverless AWS)** build of this project.
For each piece of the stack: **what it is**, **how we use it here** (concrete),
**best practices**, and **the tradeoff / decision we made**. This grows as we
make more design decisions.

> Mental model to anchor everything: **storage is passive, compute is the Lambda.**
> S3 and DynamoDB just hand bytes/records to a function when asked — they never
> compute. The Lambda is the worker that loads data, does the math, and decides
> what to fetch next.

---

## The big idea: "serverless"

**What it is.** Instead of renting a server that runs (and bills) 24/7, you upload
*functions* that the cloud runs **only when called**, billing per-request and
per-millisecond. Idle = $0.

**How we use it here.** The whole RAG service is two functions (an *ingest* function
and a *query* function) plus managed storage. Nothing runs unless someone calls it.

**Tradeoff.** You trade always-on simplicity for two things: **cold starts** (the
first call after idle pays a startup penalty) and **packaging/time limits** (see
Lambda below). For a low-traffic personal tool, that trade is almost all upside —
it's the reason this project is free.

---

## AWS Lambda — the compute

**What it is.** A service that runs your code in response to an event (an HTTP
request, a queue message, a direct invoke). You hand AWS a function; it handles the
servers, scaling, and patching. You're billed on two meters:
- **Requests:** 1 per invocation. Free tier: **1,000,000/month, always free.**
- **Duration (GB-seconds):** memory allocated × wall-clock run time. Free tier:
  **400,000 GB-seconds/month, always free.**

**How we use it here.**
- **Ingest Lambda:** clone repo → filter → chunk → embed (Gemini) → write vectors to
  S3 + chunk records to DynamoDB.
- **Query Lambda:** embed the question → load vectors from S3 → cosine in memory →
  fetch top-k chunks from DynamoDB → grounded prompt → Groq → answer + citations.

**Best practices.**
- Keep functions small and single-purpose (we have exactly two).
- Allocate memory deliberately — more memory also means more CPU, so sometimes a
  bigger memory setting runs *faster and cheaper* (less duration).
- Put secrets in SSM/Secrets Manager, not hardcoded (see Secrets, once decided).
- Use the ephemeral `/tmp` (512 MB default, up to 10 GB) for transient work like the
  git clone during ingest — it's wiped between cold starts.

**Tradeoffs / decisions.**
- **Packaging limit drove our embeddings decision.** A **zip** Lambda is capped at
  **250 MB unzipped**; `sentence-transformers`+PyTorch (~200 MB+) doesn't fit. Rather
  than switch to a 10 GB **container-image** Lambda (slower cold starts, Docker/ECR
  complexity), we chose **hosted embeddings (Gemini)** so the Lambda just makes an
  HTTPS call and stays tiny. → *Decision 1.*
- **"Paying to wait."** Lambda bills wall-clock duration **including time spent
  waiting on a network call** (e.g. the Gemini/Groq API). At our scale this is a
  rounding error inside the free tier, but it's a real serverless cost gotcha worth
  knowing.
- **15-minute max runtime.** Plenty for our one-shot ingest. The binding limit on the
  ingest *request* is actually API Gateway's 29 s, not Lambda — see API Gateway.

---

## Amazon S3 — object storage (the vector index)

**What it is.** "Simple Storage Service" — a giant, durable store of **objects**
(files), each addressed by a key (path). You read/write whole blobs. Cheap, ~11 nines
of durability. Free tier: **5 GB**.

**How we use it here.** S3 holds the **vector index**: `vectors.npy` (the float32
matrix of embeddings, one row per chunk) + `chunk_ids.json` (row → chunk-id mapping).
The query Lambda downloads these, does brute-force cosine in memory, and gets the
top-k ids. **The raw cloned repo is *not* stored in S3** — it's processed in the
ingest Lambda's `/tmp` and discarded.

**Best practices.**
- Block all public access (the index is internal; only our Lambdas read it).
- Use clear key naming (e.g. `index/vectors.npy`).
- Enable versioning if you want to roll back an index re-build (optional for us).

**Tradeoffs / decisions.**
- S3 is perfect for **blobs you read whole** (our vector matrix) but bad for
  "fetch one record out of many" — that's DynamoDB's job. This split is exactly
  *Decision 2*.

---

## Amazon DynamoDB — NoSQL database (chunk metadata + eval results)

**What it is.** A fully-managed **key-value / document** database. You design around
**access patterns**, not joins: pick a **partition key** (and optional sort key) that
matches how you'll look data up. Single-digit-millisecond reads by key. Free tier:
**25 GB + 25 read/write capacity units**.

**How we use it here.**
- **`chunks` table:** partition key = chunk `id` (`path:start-end`); attributes
  `path`, `start_line`, `end_line`, `text`. The query Lambda computes top-k ids from
  the S3 vectors, then `BatchGetItem`s **only those k records** — it never loads the
  whole corpus into memory.
- **`eval_results` table:** one record per eval run (scores, timestamp) so we can
  track the headline metric over time.

**Best practices.**
- Model for the query you actually run. Ours is "get item by id" → a plain partition
  key is the right (and simplest) design.
- Use **BatchGetItem** to fetch many keys in one call (we fetch the top-k together).
- Use on-demand (pay-per-request) capacity for spiky/low traffic — no capacity to
  tune, and it fits the free tier for us.

**Tradeoffs / decisions.**
- We chose **proper modeling (Decision 2, option B)**: chunk text in DynamoDB rather
  than bundled in the S3 JSON, *despite* our corpus being tiny. The functional payoff
  is the BatchGetItem-only-the-top-k pattern; the real reason is **learning NoSQL key
  design + batch reads** where they genuinely fit.

---

## Amazon API Gateway — the HTTP front door

**What it is.** A managed service that exposes your Lambdas as HTTP endpoints,
handling routing, throttling, and (optionally) auth/keys. Free tier covers our
request volume.

**How we use it here.** Two routes:
- `POST /query` → Query Lambda (**synchronous** — returns the answer in the response).
- `POST /ingest` → Ingest Lambda (**asynchronous** — see below).

**Best practices.**
- Throttle to protect downstream cost (our Lambdas call paid-quota APIs).
- Return proper status codes (`202 Accepted` for async work, `200` for query).

**Tradeoffs / decisions.**
- **The 29-second hard timeout drove Decision 3.** API Gateway cuts off any
  synchronous response after ~29 s. Ingest (clone + embed many chunks, rate-limited)
  can exceed that, so we made **ingest asynchronous**: `POST /ingest` fires the Lambda
  and immediately returns `202 Accepted`; the Lambda then works for up to 15 min in
  the background. The fast query path stays synchronous. → *Decision 3.*

---

## Google Gemini embeddings — hosted `text-embedding-004`

**What it is (non-AWS).** A hosted API that turns text into a fixed-length vector.
Free tier: ~1,500 req/day, no card. Reuses the `google-genai` SDK we already added.

**How we use it here.** A new `EmbeddingProvider` implementation. Called in two places:
embedding every chunk during ingest, and embedding the question during query.

**Tradeoffs / decisions.** Chose hosted (Decision 1) to keep Lambdas tiny. Chose
Gemini specifically because we already have its SDK. A **code-specialized** embedder
(e.g. Voyage `voyage-code-3`) would likely score higher on our retrieval metric and
is a great future A/B experiment — but Gemini keeps moving parts minimal for now.

---

## Groq — hosted LLM (answer generation)

**What it is (non-AWS).** Fast, free-tier LLM inference (Llama models). No embeddings —
that's why embeddings come from Gemini.

**How we use it here.** The `LLMProvider` the query Lambda calls to turn
question + retrieved chunks into a grounded, cited answer. Unchanged from Phase 0.

---

## The pluggable-provider pattern (why Phase 1 is easy)

The query/ingest logic depends only on three **interfaces** — `EmbeddingProvider`,
`VectorStore`, `LLMProvider` (in `app/types.py`). Phase 1 is mostly "write the
*cloud* implementations" (S3/DynamoDB-backed `VectorStore`, Gemini `EmbeddingProvider`)
without touching the core logic. This is both good design and the single best thing
to explain in an interview: *"I kept retrieval/embeddings/LLM swappable, so moving
from local files to S3+DynamoDB touched zero query logic."*

---

## Decision log (Phase 1)

1. **Embeddings in the cloud → hosted API (Gemini `text-embedding-004`).** Avoids the
   250 MB zip-Lambda limit; keeps functions tiny and free.
2. **Data layout → proper modeling.** Vectors in S3; chunk text/metadata in a
   DynamoDB `chunks` table; eval results in a DynamoDB `eval_results` table.
3. **Ingest trigger → asynchronous `POST /ingest` (202 Accepted).** Dodges API
   Gateway's 29 s timeout; ingest runs up to 15 min in the background.
4. _(pending — secrets management for the Lambda's API keys)_
5. _(pending — API protection / abuse control)_
6. _(pending — Terraform layout + GitHub Actions CI)_

---

## Glossary

- **Cold start:** the extra latency on the first invocation after idle, while AWS
  provisions and initializes the function. Subsequent "warm" calls are fast.
- **GB-second:** Lambda's duration unit = memory (GB) × seconds of run time. The free
  tier is 400,000/month.
- **Always-free vs 6-month:** some services (Lambda, DynamoDB, S3 within caps) are
  *permanently* free up to monthly limits; the **$100–$200 Free-plan credits** are a
  separate, time-boxed pool that covers anything beyond those caps.
- **Ephemeral `/tmp`:** scratch disk a Lambda gets during execution (512 MB default),
  wiped between cold starts — where we clone the repo during ingest.
- **BatchGetItem:** one DynamoDB call that fetches many items by key — we use it to
  pull just the top-k chunks.
