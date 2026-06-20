# Serverless-Rag — chat with a codebase

Point it at a code repository, then ask natural-language questions and get answers
that are **grounded in the actual code and cite the exact files + line ranges** they
came from — and that say *"I don't find that in the code"* when the context doesn't
support an answer. Runs locally as a CLI, or serverless on AWS (free-tier), all
provisioned as code.

---

## ⚠️ Bring your own keys — this is self-hosted, not a shared service

There is **no hosted/shared instance** of this tool. To use it, **you run it yourself
with your own API keys** (and, for the cloud version, your own AWS account). This is
deliberate so that no one else's free quotas get burned by strangers.

- **Keys are never in this repo.** Locally they live in a **gitignored `.env`**; in the
  cloud they live in **AWS SSM SecureString** parameters you set yourself. The tracked
  `.env.example` lists the variable *names* only — never values.
- **The deployed API endpoint is private.** Every request needs an `x-api-key` that only
  **you** (the deployer) hold, plus a rate limit + daily quota. Cloning this public repo
  gives you the *code* — not access to anyone's running endpoint, keys, or AWS account.
- The free providers (Groq, Gemini) each have their own free tiers. If you deploy, you're
  spending **your** free quota, protected by **your** API key. Don't share the key value.

---

## What it does

```
ingest:  repo → filter files → line-based chunks (+path/line metadata) → embed → store
query:   question → embed → top-k cosine → grounded, cite-instructed prompt → LLM → cited answer
```

Embeddings, the vector store, and the LLM are each **pluggable behind one interface**
(`app/types.py`) — swapping a vendor (or local↔cloud) touches no query/ingest logic.

---

## Run it locally (no AWS needed)

**Requirements:** Python 3.11+ and at least one free LLM key.

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1   |  Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
```
> First run downloads `all-MiniLM-L6-v2` + `torch` (a large one-time install). Locally,
> embeddings run on your machine; only answer-generation calls an LLM API.
>
> On Windows, bare `python` may hit a broken Store stub — use `.venv/Scripts/python.exe`.

**Provide your key(s)** — copy the template and fill in your own:
```bash
cp .env.example .env
# edit .env, e.g.  GROQ_API_KEY=gsk_your_own_key
```

| `LLM_PROVIDER` | Free? | Key env var | Where to get a free key |
|---|---|---|---|
| `groq` (default) | yes | `GROQ_API_KEY` | console.groq.com → API Keys |
| `gemini` | yes | `GEMINI_API_KEY` | aistudio.google.com → Get API key |
| `anthropic` | paid | `ANTHROPIC_API_KEY` | console.anthropic.com |

**Use it:**
```bash
.venv/Scripts/python.exe -m cli ingest --path .                     # index a local dir
.venv/Scripts/python.exe -m cli ingest --repo-url https://github.com/OWNER/REPO  # or a public repo
.venv/Scripts/python.exe -m cli query "Where does chunking happen?"  # grounded, cited answer
.venv/Scripts/python.exe -m eval.run_eval                            # score the golden set
```
`.env` is gitignored — never commit real keys.

---

## Deploy your own serverless instance on AWS (optional)

Provisions the whole stack with Terraform on the AWS always-free tier: S3 (vectors) +
DynamoDB (chunks) + two Lambdas + API Gateway (API-key protected) + SSM secrets +
CloudWatch. See [`docs/aws-concepts-review.md`](docs/aws-concepts-review.md) for a full
explainer and [the Phase 1 spec](docs/superpowers/specs/2026-06-19-phase1-serverless-mvp-design.md).

**Prereqs:** your own AWS account (Free plan recommended), AWS CLI configured, Terraform.
First adjust `infra/variables.tf` (`account_id`, `github_repo`) and the state-bucket name
in `infra/versions.tf` to **your** values, and bootstrap a state bucket once.

**1. Put YOUR keys into SSM (out-of-band — they never enter Terraform or git):**
```bash
aws ssm put-parameter --name /serverless-rag/groq-api-key   --type SecureString --value "$GROQ_API_KEY"   --region <your-region>
aws ssm put-parameter --name /serverless-rag/gemini-api-key --type SecureString --value "$GEMINI_API_KEY" --region <your-region>
```

**2. Build the Lambda package + deploy:**
```bash
PYTHON=.venv/Scripts/python.exe bash scripts/build_lambda.sh
cd infra && terraform init && terraform apply
```

**3. Note your private endpoint + API key (keep the key value secret):**
```bash
terraform -chdir=infra output -raw invoke_url      # your API URL
terraform -chdir=infra output -raw api_key_id      # then fetch the value:
aws apigateway get-api-key --api-key <api_key_id> --include-value --region <your-region> --query value --output text
```

**Tear it all down (no lingering cost):** `terraform -chdir=infra destroy`.

CI/CD: pushing to `main` runs the tests and deploys via **GitHub OIDC** (no AWS keys stored
in GitHub). Set the workflow's `role-to-assume` to *your* CI role ARN.

---

## Using your deployed endpoint

Both ingest **and** query run **entirely in AWS**. The ingest Lambda is a container
image (with `git` baked in), so it clones→chunks→embeds→stores server-side — no local
clone. The query Lambda serves answers. Local CLI mode (above) stays as an explicit
*dev* option.

**Index a repo into your cloud store (fully serverless):**
```bash
KEY=$(aws apigateway get-api-key --api-key <your-api-key-id> --include-value --region <your-region> --query value --output text)
curl -s -X POST "<your-invoke-url>/ingest" \
  -H "x-api-key: $KEY" -H "content-type: application/json" \
  -d '{"repo_url":"https://github.com/OWNER/REPO"}'      # returns 202; runs in the background
```
The ingest Lambda clones the repo, chunks, embeds (Gemini), and writes vectors→S3 +
chunks→DynamoDB. Watch progress in CloudWatch logs `/aws/lambda/serverless-rag-ingest`
(`ingest complete: N chunks`).
> **Limits:** the ingest Lambda has a hard **15-minute** max, and Gemini's free
> embedding tier is rate/quota limited (the embedder batches ≤100 and retries on 429
> with back-off). So this targets **small-to-moderate repos**; very large ones are
> future work (Fargate / SQS-chunked ingestion).

**Ask your endpoint a question (with YOUR api key):**
```bash
KEY=$(aws apigateway get-api-key --api-key <your-api-key-id> --include-value --region <your-region> --query value --output text)
curl -s -X POST "<your-invoke-url>/query" \
  -H "x-api-key: $KEY" -H "content-type: application/json" \
  -d '{"question":"How does it handle video streaming?", "k":4}'
```
Response shape: `{answer, citations:[{path,start_line,end_line}], refused, latency_ms, tokens}`.

**Tips:** `403` = missing/wrong key · `409` = no index yet · default `k` is 8, but on
**large-file repos lower `k`** (e.g. `"k":4`) — a big retrieved context can make generation
exceed API Gateway's hard **29-second** timeout (`504`).

---

## Current eval score (local, this repo)

Golden set: 6 questions about this repo. Provider: Groq (`llama-3.3-70b-versatile`).

- **Retrieval hit-rate: 5/6 (83%)** · **Answer correctness: 5/6 (83%)**

The two misses are honest eval signal (deterministic keyword scoring is brittle; and
prose docs out-rank code for one conceptual query — the classic pure-vector weakness that
motivates hybrid retrieval). This is the number that moves as you tune chunk size, `k`,
the prompt, the corpus, and the scoring method.

---

## Build phases & docs

Phase 0 (local proof) and Phase 1 (serverless AWS) are complete; Phase 2 (tool-calling
agent) and Phase 3 (OpenSearch / tree-sitter / container ingest / UI) are future work.
See [`docs/PROJECT.md`](docs/PROJECT.md), the [specs](docs/superpowers/specs/), and the
[AWS concepts review](docs/aws-concepts-review.md).
