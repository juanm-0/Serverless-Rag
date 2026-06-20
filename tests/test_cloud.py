import io
import json
import urllib.error

import app.cloud as cloud


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_cloud_post_sends_key_and_returns_parsed(monkeypatch):
    monkeypatch.setenv("INVOKE_URL", "https://x.example.com/prod")
    monkeypatch.setenv("API_KEY", "secret-key")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["data"] = req.data
        return _FakeResp(200, json.dumps({"answer": "ok"}))

    monkeypatch.setattr(cloud.urllib.request, "urlopen", fake_urlopen)
    status, body = cloud.cloud_post("/query", {"question": "q"})

    assert status == 200
    assert body == {"answer": "ok"}
    assert captured["url"] == "https://x.example.com/prod/query"
    assert "secret-key" in captured["headers"].values()  # x-api-key header sent
    assert json.loads(captured["data"]) == {"question": "q"}


def test_cloud_post_strips_trailing_slash_on_invoke_url(monkeypatch):
    monkeypatch.setenv("INVOKE_URL", "https://x.example.com/prod/")
    monkeypatch.setenv("API_KEY", "k")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _FakeResp(202, "")

    monkeypatch.setattr(cloud.urllib.request, "urlopen", fake_urlopen)
    status, body = cloud.cloud_post("/ingest", {"repo_url": "https://github.com/a/b"})
    assert status == 202
    assert body == {}  # empty body parses to {}
    assert captured["url"] == "https://x.example.com/prod/ingest"


def test_cloud_post_returns_status_and_body_on_http_error(monkeypatch):
    monkeypatch.setenv("INVOKE_URL", "https://x.example.com/prod")
    monkeypatch.setenv("API_KEY", "k")

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message":"Forbidden"}')
        )

    monkeypatch.setattr(cloud.urllib.request, "urlopen", fake_urlopen)
    status, body = cloud.cloud_post("/query", {"question": "q"})
    assert status == 403
    assert body == {"message": "Forbidden"}
