Smart constraints, the "don't pay anything" one especially, because it actually dictates the architecture. Let me ground the cost guidance in current AWS terms first, since AWS changed its free tier in 2025.Orchestrated explanation of flows, brainstormed non-health project ideas, outlined next stepsOrchestrated explanation of flows, brainstormed non-health project ideas, outlined next stepsGood news on the cost front, and it actually makes the design decision for us. As of the July 2025 change, new AWS accounts no longer get the old 12‑month free tier; instead you choose a Free Plan at signup with up to $200 in credits ($100 instant, $100 from onboarding tasks), valid for about 6 months, and crucially, on the Free Plan AWS does not bill you beyond your credits; the account simply suspends rather than charging your card. On top of that, 30+ "always free" services (Lambda, DynamoDB, S3 within monthly caps) remain and don't consume credits. Tech Bytes + 2
Your "don't pay anything" rule translates into four concrete guardrails:

Pick the Free Plan at signup (not Paid), it's the hard stop that suspends instead of billing.
Lean on always‑free serverless (Lambda, DynamoDB, S3) so you barely touch credits at all.
Avoid anything that runs 24/7 (RDS, OpenSearch, Fargate, an EC2 left on), those quietly drain credits. This is why the architecture below is fully serverless.
Set an AWS Budget alarm at $1 (it's also one of the tasks that earns you $20) and set CloudWatch log retention to 30 days, because CloudWatch log groups default to infinite retention and accrue charges silently. InfraTally

The architecture and what each piece is for
Same RAG service we discussed, but deliberately serverless so it stays free. Here's each AWS component and why it's there, which is exactly what you'd walk an interviewer through:

API Gateway — the front door. Exposes two HTTP endpoints (/ingest, /query). Teaches you request routing, throttling, and how a managed API layer sits in front of compute. (Draws on credits, pennies.)
Lambda (×2) — your compute, with no server to manage. An Ingest function (chunk → embed → store vectors) and a Query function (embed the question → retrieve → call the LLM → return a cited answer). Teaches event‑driven serverless, cold starts, packaging, and IAM execution roles. Always free within 1M requests/month.
S3 — object storage for two things: the raw uploaded documents, and the vector index written as a file. Teaches buckets, keys, and lifecycle. Always free within 5GB.
DynamoDB — a NoSQL table for chunk metadata and your eval results. Teaches partition/sort keys and NoSQL data modeling (which is itself on several of your target JDs). Always free within 25GB.
Bedrock (or an external LLM) — the AI layer: embeddings + answer generation. Using Bedrock keeps it AWS‑native and is one of the credit‑earning onboarding tasks; an external free‑tier model (Gemini/Groq) or local embeddings is the swap‑in if you want zero credit use.
CloudWatch — logs, custom metrics (latency, retrieval hits), a dashboard, and alarms. This is your observability story, which BuildOps/PocketHealth/Trader all want.
IAM — least‑privilege roles tying it together (Lambda can read S3 + write DynamoDB, nothing more). Teaches the security model every AWS JD assumes.
Terraform — provisions all of the above as code (closes your IaC gap), and lets you terraform destroy to guarantee nothing lingers.
GitHub Actions — runs the eval suite and deploys on push (closes the CI/CD + GitHub‑Actions gap Trader named).

The one design choice worth highlighting, because it's a great interview moment: I'd do vector search as brute‑force cosine similarity inside the Query Lambda rather than standing up a vector database. At a few hundred to a few thousand chunks that's genuinely the right call, it's free, it has no running instance, and it forces you to understand what a vector search actually does. Then you say: "I'd swap to OpenSearch or pgvector once the corpus or latency made the managed option worth the cost", which demonstrates exactly the latency/cost/reliability judgment those roles screen for.

Reading it: both flows share the same path. Ingest = you upload docs → API Gateway → Ingest Lambda chunks them, gets embeddings from Bedrock, and writes vectors to S3 + metadata to DynamoDB. Query = you ask a question → API Gateway → Query Lambda embeds it, pulls the closest chunks (brute‑force from S3), asks Bedrock to answer using only those chunks, and returns a cited answer back up the same path. The dashed band is the "grown‑up engineer" layer that turns a script into a project, and notice everything teal is genuinely free and only two amber boxes ever touch your credits.


