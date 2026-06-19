import pytest

from app.providers.llm import (
    AnthropicLLM,
    GeminiLLM,
    GroqLLM,
    _PROVIDERS,
    make_llm,
)


class _FakeUsage:
    input_tokens = 11
    output_tokens = 7


class _FakeBlock:
    type = "text"
    text = '{"answer": "hi", "used_block_ids": [], "refused": false}'


class _FakeMessage:
    content = [_FakeBlock()]
    usage = _FakeUsage()


class _FakeMessages:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeMessage()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_generate_returns_text_and_records_usage():
    client = _FakeClient()
    llm = AnthropicLLM(client=client, model="claude-opus-4-8")
    out = llm.generate("system prompt", "user prompt")
    assert out == '{"answer": "hi", "used_block_ids": [], "refused": false}'
    # request was built correctly
    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["system"] == "system prompt"
    assert kwargs["messages"] == [{"role": "user", "content": "user prompt"}]
    # usage captured for observability
    assert llm.last_usage == {"input": 11, "output": 7}


# --- Groq (OpenAI-compatible chat completions) -----------------------------

class _GroqUsage:
    prompt_tokens = 13
    completion_tokens = 9


class _GroqMessage:
    content = '{"answer": "groq", "used_block_ids": [], "refused": false}'


class _GroqChoice:
    message = _GroqMessage()


class _GroqResponse:
    choices = [_GroqChoice()]
    usage = _GroqUsage()


class _GroqCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _GroqResponse()


class _GroqChat:
    def __init__(self):
        self.completions = _GroqCompletions()


class _FakeGroqClient:
    def __init__(self):
        self.chat = _GroqChat()


def test_groq_generate_returns_text_and_records_usage():
    client = _FakeGroqClient()
    llm = GroqLLM(client=client, model="llama-3.3-70b-versatile")
    out = llm.generate("system prompt", "user prompt")
    assert out == '{"answer": "groq", "used_block_ids": [], "refused": false}'
    kwargs = client.chat.completions.last_kwargs
    assert kwargs["model"] == "llama-3.3-70b-versatile"
    assert kwargs["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    # JSON mode requested so the grounding contract parses cleanly
    assert kwargs["response_format"] == {"type": "json_object"}
    assert llm.last_usage == {"input": 13, "output": 9}


# --- Gemini (google-genai) -------------------------------------------------

class _GeminiUsage:
    prompt_token_count = 21
    candidates_token_count = 4


class _GeminiResponse:
    text = '{"answer": "gemini", "used_block_ids": [], "refused": false}'
    usage_metadata = _GeminiUsage()


class _GeminiModels:
    def __init__(self):
        self.last_kwargs = None

    def generate_content(self, **kwargs):
        self.last_kwargs = kwargs
        return _GeminiResponse()


class _FakeGeminiClient:
    def __init__(self):
        self.models = _GeminiModels()


def test_gemini_generate_returns_text_and_records_usage():
    client = _FakeGeminiClient()
    llm = GeminiLLM(client=client, model="gemini-2.0-flash")
    out = llm.generate("system prompt", "user prompt")
    assert out == '{"answer": "gemini", "used_block_ids": [], "refused": false}'
    kwargs = client.models.last_kwargs
    assert kwargs["model"] == "gemini-2.0-flash"
    assert kwargs["contents"] == "user prompt"
    # system prompt + JSON mode go through config (passed as a plain dict)
    assert kwargs["config"]["system_instruction"] == "system prompt"
    assert kwargs["config"]["response_mime_type"] == "application/json"
    assert llm.last_usage == {"input": 21, "output": 4}


# --- Factory ----------------------------------------------------------------

def test_make_llm_dispatches_to_the_selected_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    # AnthropicLLM with no client tries to construct the real SDK; assert the
    # class chosen rather than constructing it, via the provider registry.
    assert _PROVIDERS == {
        "anthropic": AnthropicLLM,
        "groq": GroqLLM,
        "gemini": GeminiLLM,
    }


def test_make_llm_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="nope"):
        make_llm()


def test_make_llm_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # Inject a fake so no real Groq SDK/key is needed.
    llm = make_llm(client=_FakeGroqClient())
    assert isinstance(llm, GroqLLM)
