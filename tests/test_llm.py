from app.providers.llm import AnthropicLLM


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
