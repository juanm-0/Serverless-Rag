import os

import pytest

from app.config import env, load_secrets_from_ssm, SSM_PARAMETERS


class _FakeSSM:
    def __init__(self, values):
        self._values = values
        self.calls = []

    def get_parameter(self, Name, WithDecryption):
        self.calls.append((Name, WithDecryption))
        return {"Parameter": {"Value": self._values[Name]}}


def test_load_secrets_sets_env_from_ssm(monkeypatch):
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    fake = _FakeSSM(
        {
            "/serverless-rag/groq-api-key": "gsk_fake",
            "/serverless-rag/gemini-api-key": "gem_fake",
        }
    )
    load_secrets_from_ssm(ssm_client=fake)
    assert os.environ["GROQ_API_KEY"] == "gsk_fake"
    assert os.environ["GEMINI_API_KEY"] == "gem_fake"
    # decryption was requested
    assert all(decrypt is True for _name, decrypt in fake.calls)


def test_load_secrets_does_not_overwrite_existing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "already-set")
    monkeypatch.setenv("GEMINI_API_KEY", "already-set")
    fake = _FakeSSM({})  # would KeyError if it tried to fetch
    load_secrets_from_ssm(ssm_client=fake)
    assert os.environ["GROQ_API_KEY"] == "already-set"
    assert fake.calls == []  # nothing fetched


def test_env_returns_value_and_raises_when_missing(monkeypatch):
    monkeypatch.setenv("INDEX_BUCKET", "my-bucket")
    assert env("INDEX_BUCKET") == "my-bucket"
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(KeyError):
        env("MISSING_VAR")


def test_ssm_parameter_map_shape():
    assert SSM_PARAMETERS == {
        "/serverless-rag/groq-api-key": "GROQ_API_KEY",
        "/serverless-rag/gemini-api-key": "GEMINI_API_KEY",
    }
