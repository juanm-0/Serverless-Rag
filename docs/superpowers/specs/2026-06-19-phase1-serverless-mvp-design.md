# Phase 1 — Serverless MVP on AWS — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design), pending implementation plan
**Source of truth:** [`docs/PROJECT.md`](../../PROJECT.md). Builds on the Phase 0 core
([`2026-06-19-phase0-local-rag-design.md`](2026-06-19-phase0-local-rag-design.md)).
Learning companion: [`docs/aws-concepts-review.md`](../../aws-concepts-review.md).

---

## 1. Purpose & Scope

Deploy the **exact Phase 0 RAG core** to AWS as a serverless service, provisioned as
code, staying within always-free tiers. The core logic (chunk → embed → cosine →
grounded answer → cite) is unchanged; Phase 1 implements the **cloud versions of the
existing provider interfaces** and the surrounding plumbing.

**Exit criterion (PROJECT.md):** `POST /query` returns a grounded, cited answer from
AWS, deploys via CI, and `terraform destroy` tears it all down cleanly.

### In scope
- Cloud `EmbeddingProvider` (hosted Gemini) and cloud `VectorStore` (S3 + DynamoDB).
- Two Lambdas (ingest, query) + Lambda handlers adapting API Gateway events.
- API Gateway REST API: `POST /ingest` (async), `POST /query` (sync), with an API-key
  usage plan (throttle + daily quota).
- Secrets via SSM Parameter Store (SecureString).
- Terraform for all resources, with S3+DynamoDB remote state.
- GitHub Actions CI/CD via OIDC (tests + `plan` on PR, `apply` on `main`).
- CloudWatch logging with explicit 30-day retention.

### Out of scope (deferred)
- Live re-indexing on commit; user accounts / multi-tenant; a polished UI.
- Container-image Lambdas / OpenSearch / tree-sitter (Phase 3).
- DynamoDB-per-chunk *as the only store* of vectors (vectors stay as an S3 blob).
- An ingest **status-tracking** API (async failures surface in CloudWatch logs only).
- Running the live eval on every push (it is a manual/occasional job).

## 2. Decisions (with rationale)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Hosted embeddings — Gemini `text-embedding-004`** | Avoids the 250 MB zip-Lambda limit (torch doesn't fit); keeps Lambdas tiny; reuses `google-genai`. |
| 2 | **Proper data modeling** — vectors in S3, chunk text/metadata in DynamoDB `chunks`, eval results in DynamoDB `eval_results` | Query Lambda computes top-k from S3 vectors then `BatchGetItem`s only those k chunks; teaches NoSQL key design + batch reads. |
| 3 | **Async ingest** — `POST /ingest` returns `202`, Lambda runs in background (≤15 min) | Dodges API Gateway's ~29 s sync timeout; teaches async invocation. |
| 4 | **SSM Parameter Store SecureString** for `GROQ_API_KEY` / `GEMINI_API_KEY` | Free, encrypted, IAM-gated; secret value set out-of-band so it never enters Git/Terraform state. |
| 5 | **API Gateway usage plan** (API key + throttle + daily quota) | Abuse control (not user auth) for the public endpoint; protects downstream free quotas. Requires REST API (HTTP API lacks API keys). |
| 6 | **Terraform with S3+DynamoDB remote state; GitHub Actions via OIDC** | Shared state enables CI deploys; OIDC avoids long-lived AWS keys in GitHub. |

Account facts: AWS account `serverless-rag` (585242447302), region **ca-central-1**,
Free plan, admin IAM user `juanm-admin`, $1 zero-spend budget, MFA on root.

## 3. Architecture

```
                        ┌─────────────── AWS (ca-central-1) ───────────────┐
  caller ──x-api-key──▶ │  API Gateway (REST, usage plan: key+throttle)     │
                        │     ├─ POST /query   ─(sync proxy)──▶ Query Lambda │
                        │     └─ POST /ingest  ─(async, 202)──▶ Ingest Lambda│
   Gemini (embeddings) ◀┼───── both Lambdas                                  │
   Groq   (LLM)         ◀┼───── query Lambda                                 │
                        │   S3:  index/vectors.npy, index/chunk_ids.json     │
                        │   DynamoDB: chunks (id→text+meta), eval_results    │
                        │   SSM SecureString: groq/gemini keys               │
                        │   CloudWatch logs (30-day retention)               │
                        └────────────────────────────────────────────────────┘
   Terraform (S3+Dynamo remote state) provisions all · GitHub Actions deploys via OIDC
```

## 4. Components / New Code

Core `app/` logic (`chunk`, `retrieve`, `generate`, `query`, `types`) is **unchanged**.
New units, each behind an existing interface or as a thin adapter:

```
app/
  config.py             # load secrets from SSM at cold start; select providers via env
  providers/
    embeddings.py       # ADD GeminiEmbeddings (implements EmbeddingProvider)
    vectorstore.py      # ADD cloud store: S3 (vectors) + DynamoDB (chunks)
handlers/
  ingest_handler.py     # Lambda entry: API Gateway event -> app.ingest (async worker)
  query_handler.py      # Lambda entry: API Gateway event -> app.query -> JSON response
infra/
  *.tf                  # all AWS resources (see §6)
.github/workflows/
  ci.yml                # tests + terraform plan on PR; apply on main (OIDC)
```

**`GeminiEmbeddings`** — implements `embed(texts) -> list[list[float]]` via the
`google-genai` client (`text-embedding-004`); reads `GEMINI_API_KEY`. Injectable client
for tests.

**Cloud `VectorStore`** — keeps the `add`/`search` protocol but is backed by AWS:
- *Ingest side:* `add(chunks, vectors)` accumulates; a `persist()` step writes
  `vectors.npy` + `chunk_ids.json` to **S3** and `BatchWriteItem`s chunk records to the
  **DynamoDB `chunks` table**.
- *Query side:* a loader reads the S3 vectors + id list into memory; `search(q, k)`
  computes cosine in memory → top-k ids → `BatchGetItem`s those chunk records from
  DynamoDB → returns `Hit`s. Chunk *text* is never bulk-loaded into the Lambda — only
  the top-k are fetched.

**`config.py`** — fetches `GROQ_API_KEY` / `GEMINI_API_KEY` from SSM once per cold start
(cached), and constructs providers (`make_llm`, `GeminiEmbeddings`, cloud store). Locally
it still honors `.env` so the CLI/eval keep working unchanged.

**Handlers** — parse the API Gateway event, call the relevant `app` function, and
serialize the result (`query_handler` returns the existing `QueryResult` shape as JSON;
`ingest_handler` is invoked asynchronously and logs progress/result to CloudWatch).

## 5. Data Flow

**Ingest (async):** `POST /ingest {repo_url}` → API Gateway invokes the ingest Lambda
asynchronously, returns **202 Accepted** immediately → Lambda: clone to `/tmp` → filter
→ chunk → embed (Gemini) → write vectors to S3 + chunks to DynamoDB → log completion.

**Query (sync):** `POST /query {question}` → query Lambda: embed question (Gemini) →
load vectors+ids from S3 → cosine top-k → `BatchGetItem` chunks → grounded prompt →
Groq → parse → return `{answer, citations[], refused, latency_ms, tokens}`. Log latency,
retrieved chunk ids, token usage to CloudWatch.

## 6. AWS Resources (Terraform)

- **S3 bucket** (index): private, holds `index/vectors.npy` + `index/chunk_ids.json`.
- **DynamoDB tables:** `chunks` (PK `id`), `eval_results` (PK run id). On-demand capacity.
- **Lambdas:** `ingest`, `query` (zip packages — tiny, since embeddings are hosted).
- **API Gateway REST API:** `POST /query` (Lambda proxy, sync), `POST /ingest` (async
  Lambda invocation, returns 202); **usage plan** with API key + throttle + daily quota.
- **SSM Parameters:** `/serverless-rag/groq-api-key`, `/serverless-rag/gemini-api-key`
  (SecureString; values set via CLI, **referenced** by Terraform, not stored in it).
- **IAM roles:** per-Lambda execution roles (least privilege — query reads S3+chunks+SSM;
  ingest also writes S3+chunks); a CI deploy role trusted via the GitHub OIDC provider.
- **CloudWatch log groups:** one per Lambda, **30-day retention set explicitly**.
- **Remote state backend:** S3 state bucket + DynamoDB lock table (created once via a
  bootstrap step before `terraform init`).

## 7. Secrets Management

`GROQ_API_KEY` and `GEMINI_API_KEY` live as **SSM SecureString** parameters, set
**out-of-band** via `aws ssm put-parameter --type SecureString` (a documented one-time
step), never in Terraform. Terraform creates/references the parameters and grants each
Lambda `ssm:GetParameter` on only its parameters. Local dev keeps using `.env`.

## 8. Error Handling

- **SSM fetch fails / key missing:** fail fast with a clear logged error.
- **Query with missing/empty index:** return a clear 4xx ("no index — run ingest first").
- **Gemini/Groq API errors:** graceful error response; `generate.py` already fails closed
  to a refusal on malformed LLM JSON.
- **Async ingest failures:** surfaced in CloudWatch logs (202 already returned; no status
  API in Phase 1).
- **API Gateway:** missing/invalid `x-api-key` → 403 from the usage plan.

## 9. Testing

- **Unit:** `GeminiEmbeddings` (injected fake client); cloud `VectorStore` and handlers
  tested against **`moto`** (mocks S3/DynamoDB locally — fast, offline, free); handler
  event-shape tests; SSM loader with a fake client. All 37 existing Phase 0 tests keep
  passing untouched.
- **Infra:** `terraform validate` + `terraform plan` in CI.
- **Integration:** the live eval (`run_eval`) executed against the deployed endpoint —
  a manual/occasional run, producing the headline number from the cloud.

## 10. Delivery (Terraform + CI/CD)

- **State:** S3 remote backend + DynamoDB lock; one-time bootstrap creates the bucket +
  lock table + GitHub OIDC provider + CI role.
- **CI (GitHub Actions, OIDC auth):** on push/PR → 37 unit tests + `terraform plan`; on
  merge to `main` → `terraform apply`. No long-lived AWS keys stored in GitHub.
- **Teardown:** `terraform destroy` removes everything; SSM secrets and the state bucket
  are the only out-of-band items.

## 11. Manual Steps

**Already done:** AWS account (Free plan), region ca-central-1, root MFA, admin IAM user,
$1 budget, AWS CLI configured.

**Remaining one-time (before/at first deploy), to be detailed in the plan:**
1. Bootstrap remote state: create the state S3 bucket + DynamoDB lock table.
2. Create the GitHub OIDC identity provider + CI deploy role (Terraform or CLI).
3. Put the two API keys into SSM (`aws ssm put-parameter --type SecureString ...`).
4. Add any required GitHub repo settings for OIDC (no secrets needed beyond config).

## 12. New Dependencies

- `boto3` (AWS SDK — S3/DynamoDB/SSM; used in `providers/` + handlers/config).
- `moto` (dev — mocks AWS in unit tests).
- (`google-genai` already present from Phase 0's Gemini LLM option.)

## 13. Success Criteria

- `POST /query` (with the API key) returns a grounded, cited answer served from AWS.
- The pipeline deploys via GitHub Actions on merge to `main` (OIDC, no stored AWS keys).
- The live eval runs against the deployed endpoint and produces the headline number.
- `terraform destroy` tears everything down; the account returns to ~zero resources.
- Everything stays within always-free tiers; the $1 budget never alarms.
