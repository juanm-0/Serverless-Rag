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

**Usage plans (API keys + throttling).** API Gateway can require an `x-api-key` header
and enforce a request rate + daily quota — all config, no app code. This is **abuse
control, not user auth**: it stops a stranger who finds the URL from draining our
Groq/Gemini free quotas, without building logins/accounts.

**Tradeoffs / decisions.**
- **The 29-second hard timeout drove Decision 3.** API Gateway cuts off any
  synchronous response after ~29 s. Ingest (clone + embed many chunks, rate-limited)
  can exceed that, so we made **ingest asynchronous**: `POST /ingest` fires the Lambda
  and immediately returns `202 Accepted`; the Lambda then works for up to 15 min in
  the background. The fast query path stays synchronous. → *Decision 3.*
- **Public endpoint → API key + throttling (Decision 5).** Both routes sit behind a
  usage plan requiring `x-api-key`, with rate + daily-quota caps. Protects downstream
  paid-quota APIs for free. Consistent with PROJECT.md's "no user accounts" — this is
  abuse control, not authentication.

---

## AWS Systems Manager Parameter Store — secrets management

**What it is.** A managed store for configuration and secrets, addressed by name
(e.g. `/serverless-rag/groq-api-key`). A **SecureString** parameter is **encrypted at
rest** with KMS (the AWS-managed key is free). **Standard parameters are free.**

**How we use it here.** The `GROQ_API_KEY` and `GEMINI_API_KEY` live as SecureString
parameters. Each Lambda reads them once at cold start (`ssm:GetParameter`) and caches
them — the cloud equivalent of our local `.env`.

**Best practices (this is the important part).**
- **Put the secret *value* in out-of-band, via the CLI** (`aws ssm put-parameter
  --type SecureString ...`) — **never in Terraform**. Terraform only creates/references
  the parameter and grants the Lambda IAM permission to read it. Result: **the secret
  never touches Git or Terraform state.**
- Scope the Lambda's IAM policy to *just* the parameters it needs (least privilege).
- Namespace parameters per app (`/serverless-rag/...`).

**Tradeoffs / decisions.** We chose **SSM SecureString (Decision 4, option B)** over
plain Lambda env vars (which sit in plaintext in the function config and Terraform
state) and over **Secrets Manager** (purpose-built with rotation, but ~$0.40/secret/
month — not free, and overkill here). SSM is free, encrypted, IAM-gated, and teaches
the standard "keep secrets out of IaC, read at runtime" pattern.

---

## Google Gemini embeddings — hosted `gemini-embedding-001`

**What it is (non-AWS).** A hosted API that turns text into a fixed-length vector.
Free tier exists (no card) but is **tokens-per-minute limited**. Reuses the
`google-genai` SDK we already added. (We initially specced `text-embedding-004`;
it's retired — the current GA model is `gemini-embedding-001`.)

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

## IAM — least-privilege permissions

**What it is.** Identity and Access Management: *who* (users, roles) can do *what* on
*which* resources. A **role** is an identity a service (like a Lambda) assumes to get
permissions — no stored credentials.

**How we use it here.** Each Lambda runs as a role granting *exactly* what it needs:
the query Lambda can read the S3 index, `BatchGetItem` the `chunks` table, and read
its SSM parameters — nothing else. The ingest Lambda can additionally write S3 +
`BatchWriteItem` chunks. CI assumes a separate deploy role via OIDC.

**Best practice / tradeoff.** Least privilege: start from nothing and add only the
specific actions/resources required. More policies to write than "give it admin," but
it's the security model every AWS role assumes — and it limits blast radius if a
function is ever compromised.

---

## Terraform — infrastructure as code

**What it is.** You declare your cloud resources in `.tf` files; Terraform diffs that
against a **state file** (its record of what exists) and makes reality match. `plan`
previews changes; `apply` makes them; `destroy` tears it all down.

**How we use it here.** All of the above — S3 bucket, DynamoDB tables, two Lambdas,
API Gateway + usage plan, IAM roles, CloudWatch log groups, SSM parameter references —
is defined in `infra/*.tf`. `terraform destroy` guarantees nothing lingers to cost money.

**Best practices / decisions.**
- **Remote state in S3 + a DynamoDB lock table (Decision 6).** State lives in S3 so
  both your laptop *and* CI share it; the DynamoDB lock prevents two `apply`s at once.
  Required for CI-based deploys. One-time **bootstrap**: create the bucket + lock table
  via CLI before Terraform uses them (the classic chicken-and-egg).
- Set **CloudWatch log retention explicitly** (30 days) on every log group — the
  default is *infinite*, which silently accrues cost. This is the one free-tier
  watch-item worth remembering.

---

## GitHub Actions — CI/CD

**What it is.** GitHub's built-in automation: workflows run on events (push, PR, merge).

**How we use it here (Decision 6).**
- **On every push/PR:** the 37 unit tests + `terraform plan` (read-only preview).
- **On merge to `main`:** `terraform apply` (deploy).
- **Live eval:** run manually/occasionally, not per-push (it burns API quota).

**Best practice / tradeoff.** **GitHub OIDC** for AWS auth: CI assumes an IAM role via
short-lived tokens — **no long-lived AWS keys stored in GitHub**. More setup (an IAM
OIDC provider + a repo-scoped role) than pasting access keys into secrets, but it
removes the single most common CI credential-leak vector.

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
4. **Secrets management → SSM Parameter Store SecureString.** Keys stored encrypted,
   set via CLI (out of Terraform), read by Lambdas at runtime via IAM. Free.
5. **API protection → API Gateway usage plan (API key + throttling + daily quota).**
   Abuse control for the public endpoint; not user auth. Free.
6. **Delivery → Terraform with S3+DynamoDB remote state; GitHub Actions CI/CD via
   OIDC.** Unit tests + `plan` on PRs, `apply` on `main`, live eval manual. CloudWatch
   log retention set to 30 days explicitly.

---

## Lessons from the live deploy (gotchas the moto tests couldn't catch)

These are the real-world surprises hit while deploying — the kind of thing local
mocks never show, and worth remembering:

1. **Linux wheels for Lambda.** numpy / pydantic-core ship as compiled wheels;
   a package built on Windows won't run on Amazon Linux. Build with
   `pip install --platform manylinux2014_x86_64 --only-binary=:all:` (the
   `scripts/build_lambda.sh` does this) so it works from any host. The package is
   ~121 MB — fine under the 250 MB zip limit *because* embeddings are hosted (no torch).
2. **DynamoDB partial success.** `BatchWriteItem`/`BatchGetItem` can return
   `UnprocessedItems`/`UnprocessedKeys` under throttling — silently dropping data if
   ignored. The store retries them. moto never returns these, so only a real deploy
   (or a fake client) exercises it.
3. **The embedding model name drifts.** `text-embedding-004` 404'd; the GA model is
   now `gemini-embedding-001`. Verify model names against the live API, don't assume.
4. **Provider batch limits.** Gemini caps `embed_content` at 100 inputs per request —
   the provider chunks calls at 100. And the free tier's tokens-per-minute cap means a
   big repo can't be embedded in one burst (throttle, or use a paid tier).
5. **Weak models and the citation contract.** The free Groq Llama wouldn't reliably
   echo long exact block ids, so citations came back empty. Switching to **numbered
   blocks** (`[1] [2] …` → integer `used_blocks`) fixed it — a good lesson in designing
   contracts for the weakest model you'll run.
6. **No `git` in the Lambda runtime — now resolved with a container image.** The
   zip runtime has no `git`, so `POST /ingest {repo_url}` couldn't clone in the
   cloud. Fixed by repackaging the **ingest** Lambda as a **container image** (base
   `public.ecr.aws/lambda/python:3.12` + `git` + deps) in **ECR**; the query Lambda
   stays a zip. Now clone→chunk→embed→store all run in the Lambda. **Zip vs image:**
   zip ≤250 MB unzipped, fast cold start, no system binaries; image ≤10 GB, can bake
   in `git`/system packages, slightly slower cold start. *Gotcha:* switching an
   existing function zip→image can't be done in place — Terraform must replace it,
   and the same-name create can 409 if the old function isn't gone first (delete it,
   then apply).
7. **Terraform state locking modernized.** The DynamoDB lock table is deprecated;
   Terraform ≥1.10 locks natively via S3 (`use_lockfile = true`) — one less resource.
8. **`k` is bounded by API Gateway's 29 s timeout.** On a real repo (MoneyPrinter-
   Turbo), a query at the default `k=8` returned **504 Gateway Timeout** — eight large
   code chunks made a prompt big enough that Groq generation exceeded API Gateway's
   hard 29 s synchronous limit. `k=4` answered the same question in ~1.5 s. You can't
   raise the 29 s ceiling, so for big-file corpora tune `k` down (or use a faster model,
   or move long generations to an async pattern).

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
