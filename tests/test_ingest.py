from pathlib import Path

import numpy as np

from app.ingest import iter_source_files, build_index
from app.providers.vectorstore import InMemoryVectorStore


class _FakeEmbedder:
    def embed(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _make_repo(root: Path):
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("# Title\n", encoding="utf-8")
    # things that must be skipped:
    (root / "node_modules").mkdir()
    (root / "node_modules" / "lib.js").write_text("x=1\n", encoding="utf-8")
    (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00")


def test_iter_source_files_filters_dirs_binaries_and_lockfiles(tmp_path):
    _make_repo(tmp_path)
    found = {rel for rel, _text in iter_source_files(tmp_path)}
    assert found == {"app/main.py", "README.md"}


def test_iter_source_files_skips_files_over_size_threshold(tmp_path):
    (tmp_path / "big.py").write_text("x\n" * 5000, encoding="utf-8")
    found = {rel for rel, _ in iter_source_files(tmp_path, max_bytes=100)}
    assert "big.py" not in found


def test_build_index_chunks_embeds_and_stores(tmp_path):
    _make_repo(tmp_path)
    store = InMemoryVectorStore()
    n = build_index(tmp_path, _FakeEmbedder(), store, window=60, overlap=15)
    assert n == 2  # two short source files -> one chunk each
    hits = store.search([8.0, 1.0], k=2)  # len("print('hi')") == 11; both small
    paths = sorted(h["chunk"]["path"] for h in hits)
    assert paths == ["README.md", "app/main.py"]
