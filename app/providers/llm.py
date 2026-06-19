"""Anthropic Claude LLM provider.

Defaults to claude-opus-4-8 (override with the ANTHROPIC_MODEL env var, e.g.
claude-haiku-4-5 for cheaper dev runs). Requires ANTHROPIC_API_KEY in the
environment. Pass `client=` to inject a fake in tests.
"""
from __future__ import annotations

import os
from typing import Any

from app.types import Tokens

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 4096


class AnthropicLLM:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.last_usage: Tokens = {"input": 0, "output": 0}
        if client is not None:
            self._client = client
        else:
            import anthropic  # lazy import so tests don't need the SDK installed

            self._client = anthropic.Anthropic()

    def generate(self, system: str, user: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.last_usage = {
            "input": getattr(message.usage, "input_tokens", 0),
            "output": getattr(message.usage, "output_tokens", 0),
        }
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
