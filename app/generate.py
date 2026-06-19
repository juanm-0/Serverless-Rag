"""Grounded answer generation with structured-JSON citations.

The model is given numbered context blocks and must answer ONLY from them,
returning a JSON object {answer, used_block_ids, refused}. We map the returned
block ids back to citations. Malformed JSON is treated as a refusal (fail closed).
"""
from __future__ import annotations

import json

from app.types import Citation, Hit, LLMProvider, Tokens

REFUSAL_TEXT = "I don't find that in the code."

SYSTEM_PROMPT = (
    "You are a code-comprehension assistant. Answer the question using ONLY the "
    "numbered context blocks provided. Do not use outside knowledge. If the blocks "
    "do not contain enough information to answer, you must refuse.\n\n"
    "Respond with a single JSON object and nothing else, in this exact shape:\n"
    '{"answer": "<your answer>", "used_block_ids": ["<id>", ...], "refused": <true|false>}\n'
    'Each id in used_block_ids MUST be copied verbatim from a block header. '
    'If you cannot answer from the blocks, set "refused" to true, set "used_block_ids" to [], '
    f'and set "answer" to "{REFUSAL_TEXT}"'
)


def build_user_prompt(question: str, hits: list[Hit]) -> str:
    lines = ["Context blocks:\n"]
    for hit in hits:
        c = hit["chunk"]
        lines.append(f"[{c['id']}] ({c['path']} lines {c['start_line']}-{c['end_line']})")
        lines.append(c["text"])
        lines.append("")  # blank separator
    lines.append(f"Question: {question}")
    return "\n".join(lines)


def _refusal(tokens: Tokens) -> dict:
    return {"answer": REFUSAL_TEXT, "citations": [], "refused": True, "tokens": tokens}


def generate_answer(llm: LLMProvider, question: str, hits: list[Hit]) -> dict:
    """Return {answer, citations, refused, tokens}. Latency/result-shape wiring
    happens in app.query."""
    user = build_user_prompt(question, hits)
    raw = llm.generate(SYSTEM_PROMPT, user)
    tokens: Tokens = getattr(llm, "last_usage", {"input": 0, "output": 0})

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("response must be a JSON object")
        answer = parsed["answer"]
        if not isinstance(answer, str):
            raise TypeError("answer must be a string")
        refused = bool(parsed.get("refused", False))
        used_ids = parsed.get("used_block_ids", []) or []
        if not isinstance(used_ids, list):
            raise TypeError("used_block_ids must be a list")
    except (json.JSONDecodeError, KeyError, TypeError):
        # Any structurally-invalid response fails closed to a refusal so an
        # ungrounded or malformed answer never reaches the user.
        return _refusal(tokens)

    if refused:
        return {"answer": answer, "citations": [], "refused": True, "tokens": tokens}

    by_id = {hit["chunk"]["id"]: hit["chunk"] for hit in hits}
    citations: list[Citation] = []
    for cid in used_ids:
        chunk = by_id.get(cid)
        if chunk is not None:
            citations.append(
                Citation(
                    path=chunk["path"],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                )
            )
    return {"answer": answer, "citations": citations, "refused": False, "tokens": tokens}
