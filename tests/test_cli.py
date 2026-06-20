import cli
from cli import _looks_like_url, build_parser


def test_parser_ingest_defaults_to_cloud_and_local_flag():
    parser = build_parser()
    ns = parser.parse_args(["ingest", "https://github.com/a/b"])
    assert ns.command == "ingest"
    assert ns.source == "https://github.com/a/b"
    assert ns.local is False  # cloud is the default
    assert ns.out == "index"
    assert ns.window == 60
    assert ns.overlap == 15

    ns2 = parser.parse_args(["ingest", ".", "--local"])
    assert ns2.source == "."
    assert ns2.local is True


def test_parser_query_defaults_to_cloud_and_local_flag():
    parser = build_parser()
    ns = parser.parse_args(["query", "where is auth?", "-k", "4"])
    assert ns.command == "query"
    assert ns.question == "where is auth?"
    assert ns.local is False  # cloud is the default
    assert ns.k == 4
    assert ns.index == "index"

    ns2 = parser.parse_args(["query", "where?", "--local"])
    assert ns2.local is True


def test_looks_like_url():
    assert _looks_like_url("https://github.com/a/b")
    assert _looks_like_url("http://x")
    assert _looks_like_url("git@github.com:a/b.git")
    assert not _looks_like_url(".")
    assert not _looks_like_url("/some/path")
    assert not _looks_like_url("app")


def test_cmd_query_defaults_to_cloud_endpoint(monkeypatch, capsys):
    calls = {}

    def fake_post(path, body, timeout=60):
        calls["path"] = path
        calls["body"] = body
        return 200, {
            "answer": "A.",
            "citations": [{"path": "f.py", "start_line": 1, "end_line": 2}],
            "refused": False,
            "latency_ms": 5,
            "tokens": {"input": 1, "output": 2},
        }

    monkeypatch.setattr(cli, "cloud_post", fake_post)
    rc = cli._cmd_query(build_parser().parse_args(["query", "where?", "-k", "3"]))
    assert rc == 0
    assert calls["path"] == "/query"
    assert calls["body"] == {"question": "where?", "k": 3}
    out = capsys.readouterr().out
    assert "A." in out and "f.py:1-2" in out


def test_cmd_query_cloud_reports_http_error(monkeypatch):
    monkeypatch.setattr(cli, "cloud_post", lambda *a, **k: (403, {"message": "Forbidden"}))
    rc = cli._cmd_query(build_parser().parse_args(["query", "where?"]))
    assert rc == 1


def test_cmd_ingest_defaults_to_cloud_posts_repo_url(monkeypatch):
    calls = {}

    def fake_post(path, body, timeout=60):
        calls["path"] = path
        calls["body"] = body
        return 202, {"status": "accepted"}

    monkeypatch.setattr(cli, "cloud_post", fake_post)
    rc = cli._cmd_ingest(build_parser().parse_args(["ingest", "https://github.com/a/b"]))
    assert rc == 0
    assert calls["path"] == "/ingest"
    assert calls["body"] == {"repo_url": "https://github.com/a/b"}


def test_cmd_ingest_cloud_rejects_non_url(monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("cloud_post should not be called for a non-URL source")

    monkeypatch.setattr(cli, "cloud_post", must_not_call)
    rc = cli._cmd_ingest(build_parser().parse_args(["ingest", "."]))
    assert rc == 2  # cloud ingest requires a git URL; use --local for a path
