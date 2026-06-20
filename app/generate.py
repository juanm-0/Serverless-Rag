"""Grounded answer generation with structured-JSON citations.

The model is given NUMBERED context blocks ([1], [2], ...) and must answer ONLY
from them, returning a JSON object {answer, used_blocks, refused} where
used_blocks is a list of the integer block numbers it relied on. Block numbers
are far more reliable for weaker models to produce than echoing long ids. We map
the returned numbers back to citations. Malformed JSON fails closed (refusal).
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
    '{"answer": "<your answer>", "used_blocks": [<block numbers>], "refused": <true|false>}\n'
    'used_blocks is the list of integer block numbers (the [N] labels) your answer '
    'relied on — e.g. [1, 3]. List every block you used. If you cannot answer from '
    'the blocks, set "refused" to true, "used_blocks" to [], and "answer" to '
    f'"{REFUSAL_TEXT}"'
)


def build_user_prompt(question: str, hits: list[Hit]) -> str:
    lines = ["Context blocks:\n"]
    for number, hit in enumerate(hits, start=1):
        c = hit["chunk"]
        lines.append(f"[{number}] ({c['path']} lines {c['start_line']}-{c['end_line']})")
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
        used_blocks = parsed.get("used_blocks", []) or []
        if not isinstance(used_blocks, list):
            raise TypeError("used_blocks must be a list")
    except (json.JSONDecodeError, KeyError, TypeError):
        # Any structurally-invalid response fails closed to a refusal so an
        # ungrounded or malformed answer never reaches the user.
        return _refusal(tokens)

    if refused:
        return {"answer": answer, "citations": [], "refused": True, "tokens": tokens}

    citations: list[Citation] = []
    seen: set[int] = set()
    for raw_number in used_blocks:
        try:
            index = int(raw_number) - 1  # block labels are 1-indexed
        except (TypeError, ValueError):
            continue  # ignore non-numeric junk rather than crashing
        if 0 <= index < len(hits) and index not in seen:
            seen.add(index)
            c = hits[index]["chunk"]
            citations.append(
                Citation(path=c["path"], start_line=c["start_line"], end_line=c["end_line"])
            )
    return {"answer": answer, "citations": citations, "refused": False, "tokens": tokens}
