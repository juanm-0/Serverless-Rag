"""Pluggable LLM providers behind one `generate(system, user) -> str` interface.

Pick the active provider with the `LLM_PROVIDER` env var:
  - "groq"      (default) -> GroqLLM        | key: GROQ_API_KEY       | model: GROQ_MODEL
  - "gemini"              -> GeminiLLM      | key: GEMINI_API_KEY     | model: GEMINI_MODEL
  - "anthropic"          -> AnthropicLLM   | key: ANTHROPIC_API_KEY  | model: ANTHROPIC_MODEL

Each provider records `last_usage` (input/output tokens) for observability and
requests JSON output where the SDK supports it, so the grounding contract
{answer, used_block_ids, refused} parses cleanly. Vendor SDKs are imported
lazily inside __init__ so importing this module (and the tests) needs none of
them; pass `client=` to inject a fake.
"""
from __future__ import annotations

import os
from typing import Any

from app.types import LLMProvider, Tokens

DEFAULT_MAX_TOKENS = 4096

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class AnthropicLLM:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
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


class GroqLLM:
    """Groq (OpenAI-compatible chat completions). Free tier; key: GROQ_API_KEY."""

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model or os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.max_tokens = max_tokens
        self.last_usage: Tokens = {"input": 0, "output": 0}
        if client is not None:
            self._client = client
        else:
            from groq import Groq  # lazy import; reads GROQ_API_KEY

            self._client = Groq()

    def generate(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        usage = response.usage
        self.last_usage = {
            "input": getattr(usage, "prompt_tokens", 0),
            "output": getattr(usage, "completion_tokens", 0),
        }
        return response.choices[0].message.content


class GeminiLLM:
    """Google Gemini (google-genai). Free tier; key: GEMINI_API_KEY."""

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.max_tokens = max_tokens
        self.last_usage: Tokens = {"input": 0, "output": 0}
        if client is not None:
            self._client = client
        else:
            from google import genai  # lazy import; reads GEMINI_API_KEY / GOOGLE_API_KEY

            self._client = genai.Client()

    def generate(self, system: str, user: str) -> str:
        # config is passed as a plain dict so this method needs no SDK types.
        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config={
                "system_instruction": system,
                "max_output_tokens": self.max_tokens,
                "response_mime_type": "application/json",
            },
        )
        usage = response.usage_metadata
        self.last_usage = {
            "input": getattr(usage, "prompt_token_count", 0) or 0,
            "output": getattr(usage, "candidates_token_count", 0) or 0,
        }
        return response.text


_PROVIDERS = {
    "anthropic": AnthropicLLM,
    "groq": GroqLLM,
    "gemini": GeminiLLM,
}

DEFAULT_PROVIDER = "groq"


def make_llm(**kwargs: Any) -> LLMProvider:
    """Construct the LLM provider named by the LLM_PROVIDER env var (default groq).

    Extra kwargs (e.g. client=, model=) are forwarded to the provider, which is
    handy for injecting a fake client in tests.
    """
    name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
    try:
        provider_cls = _PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown LLM_PROVIDER: {name!r} (expected one of {sorted(_PROVIDERS)})"
        ) from None
    return provider_cls(**kwargs)
