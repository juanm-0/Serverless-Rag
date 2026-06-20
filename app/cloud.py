"""HTTP client for the deployed serverless endpoint.

Reads INVOKE_URL and API_KEY from the environment (e.g. your .env). Used by the
CLI's `--cloud` mode so cloud ingest/query are pure HTTP calls to your API
Gateway endpoint — no AWS credentials needed on the caller.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import env


def cloud_post(path: str, body: dict, timeout: int = 60) -> tuple[int, dict]:
    """POST `body` as JSON to `${INVOKE_URL}{path}` with the x-api-key header.

    Returns (status_code, parsed_json). A non-JSON or empty response body
    parses to {} (or {"error": <text>} for an unparseable error body).
    """
    url = env("INVOKE_URL").rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json", "x-api-key": env("API_KEY")},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, _parse(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, _parse(exc.read().decode("utf-8", errors="replace"))


def _parse(text: str) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": text}
