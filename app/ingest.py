"""Ingestion: resolve a source, walk + filter files, chunk + embed + store."""
from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from app.chunk import DEFAULT_OVERLAP, DEFAULT_WINDOW, chunk_file
from app.types import Chunk, EmbeddingProvider, VectorStore

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "target",
    "__pycache__", ".venv", "venv", ".tox", ".idea", ".pytest_cache",
}
SKIP_FILES = {
    "package-lock.json", "poetry.lock", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum",
}
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs",
    ".c", ".h", ".cpp", ".cs", ".php", ".sh", ".md", ".txt", ".rst",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json",
}
DEFAULT_MAX_BYTES = 1_000_000  # 1 MB


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(4096)
    except OSError:
        return True


def iter_source_files(
    root: str | Path, max_bytes: int = DEFAULT_MAX_BYTES
) -> Iterator[tuple[str, str]]:
    """Yield (repo-relative-posix-path, text) for each indexable file."""
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if path.stat().st_size > max_bytes:
            continue
        if _looks_binary(path):
            continue
        rel = path.relative_to(root).as_posix()
        yield rel, path.read_text(encoding="utf-8", errors="replace")


def resolve_source(path: str | None = None, repo_url: str | None = None) -> Path:
    """Return a local directory for the source.

    If repo_url is given, clone it into a temp dir and return that. The caller
    is responsible for the temp dir's lifetime (it lives until process exit).
    """
    if path and repo_url:
        raise ValueError("provide path OR repo_url, not both")
    if path:
        return Path(path)
    if repo_url:
        dest = Path(tempfile.mkdtemp(prefix="rag-clone-"))
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            check=True,
        )
        return dest
    raise ValueError("provide either path or repo_url")


def build_index(
    root: str | Path,
    embedder: EmbeddingProvider,
    store: VectorStore,
    window: int = DEFAULT_WINDOW,
    overlap: int = DEFAULT_OVERLAP,
) -> int:
    """Chunk + embed + store every indexable file under root. Returns chunk count."""
    chunks: list[Chunk] = []
    for rel, text in iter_source_files(root):
        chunks.extend(chunk_file(rel, text, window=window, overlap=overlap))
    if not chunks:
        return 0
    vectors = embedder.embed([c["text"] for c in chunks])
    store.add(chunks, vectors)
    return len(chunks)
