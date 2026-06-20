"""Cloud config: load provider secrets from SSM, and read required env vars.

In Lambda, secrets live in SSM SecureString parameters and are fetched at cold
start (then cached in the process env). Locally, .env already populates these,
so load_secrets_from_ssm() is a no-op when the env var is already set.
"""
from __future__ import annotations

import os
from typing import Any

SSM_PARAMETERS = {
    "/serverless-rag/groq-api-key": "GROQ_API_KEY",
    "/serverless-rag/gemini-api-key": "GEMINI_API_KEY",
}


def load_secrets_from_ssm(ssm_client: Any | None = None) -> None:
    """Populate provider API keys from SSM into os.environ (idempotent).

    Only fetches a parameter when its target env var is not already set, so
    local .env values win and repeated warm invocations skip the call.
    """
    missing = {name: var for name, var in SSM_PARAMETERS.items() if not os.environ.get(var)}
    if not missing:
        return
    if ssm_client is None:
        import boto3

        ssm_client = boto3.client("ssm")
    for name, var in missing.items():
        resp = ssm_client.get_parameter(Name=name, WithDecryption=True)
        os.environ[var] = resp["Parameter"]["Value"]


def env(name: str) -> str:
    """Return a required environment variable or raise KeyError with a clear name."""
    try:
        return os.environ[name]
    except KeyError:
        raise KeyError(f"required environment variable {name!r} is not set") from None
