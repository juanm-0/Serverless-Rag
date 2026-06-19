# Phase 0 — Local RAG Proof — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local CLI that ingests a code repository, then answers natural-language questions about it with answers grounded in the retrieved code and cited to exact file paths + line ranges — plus a first eval score. No AWS, no FastAPI.

**Architecture:** A small Python package (`app/`) with three swappable provider interfaces (embeddings, vector store, LLM) defined as Protocols. Ingest walks/filters/chunks files, embeds chunks locally (sentence-transformers), and persists vectors + metadata to two files. Query embeds the question, does brute-force cosine retrieval, builds a grounded prompt, calls Claude, and parses a structured JSON answer back to citations.

**Tech Stack:** Python 3.11+, `anthropic` SDK (Claude), `sentence-transformers` + `numpy` (local embeddings + cosine), `pyyaml` (golden set), `pytest` (tests). CLI via stdlib `argparse`.

**Spec:** [`docs/superpowers/specs/2026-06-19-phase0-local-rag-design.md`](../specs/2026-06-19-phase0-local-rag-design.md). Source of truth: [`docs/PROJECT.md`](../../PROJECT.md).

**Code-review checkpoints:** This plan has three review checkpoints (after the retrieval core, after the generation path, and a final review). At each, run `/code-review` (or the `superpowers:requesting-code-review` skill) on the diff and address findings before continuing.

---

## Conventions for the implementer

- Run all commands from the repo root: `F:\Work\Side\ServerlessRag\Serverless-Rag`.
- This is Windows with **Git Bash** and **PowerShell** available. Commands below are given for PowerShell; Bash equivalents are noted where they differ.
- After Task 0 you will work inside a virtualenv. **Activate it in every new shell** before running `python`/`pytest`.
- Type hints use modern syntax (`list[str]`, `str | None`). Target Python 3.11+.
- Keep each file focused; never import a vendor SDK (`anthropic`, `sentence_transformers`) outside `app/providers/`.

---

## Task 0: Environment setup & project scaffolding

**⚠️ MANUAL STEP REQUIRED — Python is not installed.** On this machine `python` / `python3` resolve to the Windows Store stub and `pip` is missing. The user must install a real Python before anything else runs. This is a local install (not AWS) — no cloud account needed.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/providers/__init__.py`
- Create: `tests/__init__.py`
- Create: `eval/__init__.py`

- [ ] **Step 1: Install Python 3.12 (user action)**

Ask the user to run **one** of these in a normal terminal (not inside this tool), then restart the shell:

```powershell
winget install -e --id Python.Python.3.12
```
or download the installer from https://www.python.org/downloads/ and check "Add python.exe to PATH".

Verify it resolves to a real interpreter (not the WindowsApps stub):

Run: `python --version`
Expected: `Python 3.12.x` (or any 3.11+). If it prints nothing or opens the Microsoft Store, the stub is still shadowing — disable it in *Settings → Apps → Advanced app settings → App execution aliases* (turn off the `python.exe` / `python3.exe` aliases), then reopen the shell.

- [ ] **Step 2: Create the virtualenv**

Run (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```
Bash equivalent for activation: `source .venv/Scripts/activate`

Expected: prompt is prefixed with `(.venv)`; `python -c "import sys; print(sys.prefix)"` points inside `.venv`.

> If `Activate.ps1` is blocked by execution policy, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that shell, then activate again.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "serverless-rag"
version = "0.0.0"
description = "Phase 0 local RAG proof: chat with a codebase."
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40",
    "sentence-transformers>=3.0",
    "numpy>=1.26",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
rag = "cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["cli"]
packages = ["app", "app.providers"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
index/
eval/results/
.env
# sentence-transformers model cache may land here on some setups
.cache/
```

- [ ] **Step 5: Create empty package marker files**

Create these four files, each **empty**:
- `app/__init__.py`
- `app/providers/__init__.py`
- `tests/__init__.py`
- `eval/__init__.py`

- [ ] **Step 6: Install the project (editable) + dev deps**

Run:
```powershell
python -m pip install -e ".[dev]"
```
Expected: completes successfully. **Note:** this pulls in `torch` via `sentence-transformers` and is a large download (hundreds of MB) — it may take several minutes. That is expected and is the Phase-1 size tension noted in the spec.

- [ ] **Step 7: Verify pytest runs (no tests yet)**

Run: `pytest -q`
Expected: `no tests ran` (exit code 5) — that's fine; it confirms pytest is wired.

- [ ] **Step 8: Commit**

```powershell
git add pyproject.toml .gitignore app/__init__.py app/providers/__init__.py tests/__init__.py eval/__init__.py
git commit -m "chore: scaffold Phase 0 package, deps, and gitignore"
```

---

## Task 1: Interfaces (`app/types.py`)

Defines the data shapes and the three Protocols every module depends on. No vendor imports.

**Files:**
- Create: `app/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_types.py`:
```python
from app.types import Chunk, Hit, Citation, Tokens, QueryResult


def test_chunk_and_hit_are_constructible_dicts():
    chunk: Chunk = {
        "id": "app/chunk.py:1-60",
        "path": "app/chunk.py",
        "start_line": 1,
        "end_line": 60,
        "text": "def chunk_file(): ...",
    }
    hit: Hit = {"chunk": chunk, "score": 0.87}
    assert hit["chunk"]["path"] == "app/chunk.py"
    assert hit["score"] == 0.87


def test_query_result_shape():
    result: QueryResult = {
        "answer": "It happens in chunk.py.",
        "citations": [Citation(path="app/chunk.py", start_line=1, end_line=60)],
        "refused": False,
        "latency_ms": 12,
        "tokens": Tokens(input=10, output=5),
    }
    assert result["citations"][0]["path"] == "app/chunk.py"
    assert result["tokens"]["output"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.types'` (or import error for the names).

- [ ] **Step 3: Write `app/types.py`**

```python
"""Core data shapes and the three pluggable provider Protocols.

This module is the contract. ingest/chunk/retrieve/generate depend only on
the Protocols defined here — never on a concrete vendor SDK.
"""
from __future__ import annotations

from typing import Protocol, TypedDict


class Chunk(TypedDict):
    id: str          # stable id, e.g. f"{path}:{start_line}-{end_line}"
    path: str        # repo-relative file path
    start_line: int  # 1-indexed, inclusive
    end_line: int    # 1-indexed, inclusive
    text: str


class Hit(TypedDict):
    chunk: Chunk
    score: float     # cosine similarity


class Citation(TypedDict):
    path: str
    start_line: int
    end_line: int


class Tokens(TypedDict):
    input: int
    output: int


class QueryResult(TypedDict):
    answer: str
    citations: list[Citation]
    refused: bool
    latency_ms: int
    tokens: Tokens


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text. Used for chunks and queries."""
        ...


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(self, query_vector: list[float], k: int) -> list[Hit]: ...


class LLMProvider(Protocol):
    def generate(self, system: str, user: str) -> str:
        """Single-turn generation. Returns the model's raw text response."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_types.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/types.py tests/test_types.py
git commit -m "feat: add core types and pluggable provider protocols"
```

---

## Task 2: Chunking (`app/chunk.py`)

Line-based fixed-window chunking with overlap. Window 60 lines, overlap 15 (configurable).

**Files:**
- Create: `app/chunk.py`
- Test: `tests/test_chunk.py`

- [ ] **Step 1: Write the failing test**

`tests/test_chunk.py`:
```python
from app.chunk import chunk_file


def test_short_file_is_one_chunk_spanning_whole_file():
    text = "\n".join(f"line{i}" for i in range(1, 11))  # 10 lines
    chunks = chunk_file("a/b.py", text, window=60, overlap=15)
    assert len(chunks) == 1
    c = chunks[0]
    assert c["path"] == "a/b.py"
    assert c["start_line"] == 1
    assert c["end_line"] == 10
    assert c["id"] == "a/b.py:1-10"
    assert c["text"] == text


def test_empty_file_produces_no_chunks():
    assert chunk_file("empty.py", "", window=60, overlap=15) == []


def test_windowing_with_overlap_covers_all_lines():
    text = "\n".join(f"L{i}" for i in range(1, 151))  # 150 lines
    chunks = chunk_file("big.py", text, window=60, overlap=15)
    # step = window - overlap = 45 -> windows start at lines 1, 46, 91. The
    # 91-150 window already reaches the last line, so no redundant trailing
    # window (136-150, a strict subset of 91-150) is emitted.
    assert [(c["start_line"], c["end_line"]) for c in chunks] == [
        (1, 60),
        (46, 105),
        (91, 150),
    ]
    assert chunks[0]["id"] == "big.py:1-60"
    # overlap is real: line 46 appears in both chunk 0 and chunk 1
    assert "L46" in chunks[0]["text"]
    assert "L46" in chunks[1]["text"]
    assert "L150" in chunks[-1]["text"]


def test_trailing_window_emitted_only_when_it_adds_new_lines():
    text = "\n".join(f"L{i}" for i in range(1, 161))  # 160 lines
    chunks = chunk_file("big.py", text, window=60, overlap=15)
    # The 4th window (136-160) extends past the 3rd (91-150), so it is kept.
    assert [(c["start_line"], c["end_line"]) for c in chunks] == [
        (1, 60),
        (46, 105),
        (91, 150),
        (136, 160),
    ]


def test_exact_window_multiple_does_not_emit_trailing_duplicate():
    text = "\n".join(f"L{i}" for i in range(1, 61))  # exactly 60 lines
    chunks = chunk_file("x.py", text, window=60, overlap=15)
    assert len(chunks) == 1
    assert (chunks[0]["start_line"], chunks[0]["end_line"]) == (1, 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chunk.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chunk'`.

- [ ] **Step 3: Write `app/chunk.py`**

```python
"""Line-based fixed-window chunking with overlap.

Splitting on line boundaries makes start_line/end_line exact, so citations
are precise line ranges for free.
"""
from __future__ import annotations

from app.types import Chunk

DEFAULT_WINDOW = 60
DEFAULT_OVERLAP = 15


def chunk_file(
    path: str,
    text: str,
    window: int = DEFAULT_WINDOW,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split file text into overlapping line windows.

    Lines are 1-indexed and end_line is inclusive. A file shorter than one
    window becomes a single chunk spanning the whole file. Empty text yields
    no chunks.
    """
    if overlap >= window:
        raise ValueError("overlap must be smaller than window")

    lines = text.splitlines()
    n = len(lines)
    if n == 0:
        return []

    step = window - overlap
    chunks: list[Chunk] = []
    start = 0
    while start < n:
        end = min(start + window, n)
        start_line = start + 1  # 1-indexed
        end_line = end          # inclusive
        chunks.append(
            Chunk(
                id=f"{path}:{start_line}-{end_line}",
                path=path,
                start_line=start_line,
                end_line=end_line,
                text="\n".join(lines[start:end]),
            )
        )
        if end == n:  # reached the end; don't emit a trailing duplicate window
            break
        start += step
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chunk.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/chunk.py tests/test_chunk.py
git commit -m "feat: add line-based chunking with overlap and line metadata"
```

---

## Task 3: In-memory vector store (`app/providers/vectorstore.py`)

Brute-force cosine similarity, with `save()`/`load()` to `vectors.npy` + `chunks.json`.

**Files:**
- Create: `app/providers/vectorstore.py`
- Test: `tests/test_vectorstore.py`

- [ ] **Step 1: Write the failing test**

`tests/test_vectorstore.py`:
```python
from app.providers.vectorstore import InMemoryVectorStore


def _chunk(i: int):
    return {
        "id": f"f.py:{i}-{i}",
        "path": "f.py",
        "start_line": i,
        "end_line": i,
        "text": f"chunk {i}",
    }


def test_search_ranks_by_cosine_similarity():
    store = InMemoryVectorStore()
    # vec for chunk 0 points along x, chunk 1 along y
    store.add([_chunk(0), _chunk(1)], [[1.0, 0.0], [0.0, 1.0]])
    hits = store.search([0.9, 0.1], k=2)
    assert [h["chunk"]["id"] for h in hits] == ["f.py:0-0", "f.py:1-1"]
    assert hits[0]["score"] > hits[1]["score"]


def test_search_respects_k():
    store = InMemoryVectorStore()
    store.add([_chunk(0), _chunk(1), _chunk(2)], [[1, 0], [0.5, 0.5], [0, 1]])
    assert len(store.search([1.0, 0.0], k=2)) == 2


def test_search_on_empty_store_returns_empty():
    assert InMemoryVectorStore().search([1.0, 0.0], k=5) == []


def test_save_and_load_round_trip(tmp_path):
    store = InMemoryVectorStore()
    store.add([_chunk(0), _chunk(1)], [[1.0, 0.0], [0.0, 1.0]])
    store.save(tmp_path)

    loaded = InMemoryVectorStore.load(tmp_path)
    hits = loaded.search([1.0, 0.0], k=1)
    assert hits[0]["chunk"]["id"] == "f.py:0-0"
    assert hits[0]["chunk"]["text"] == "chunk 0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vectorstore.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.vectorstore'`.

- [ ] **Step 3: Write `app/providers/vectorstore.py`**

```python
"""Brute-force in-memory vector store with cosine similarity.

Persists to two files that map cleanly to S3 objects in Phase 1:
  - vectors.npy : float32 matrix, one row per chunk
  - chunks.json : list of Chunk dicts, row-aligned with the matrix
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.types import Chunk, Hit

_VECTORS_FILE = "vectors.npy"
_CHUNKS_FILE = "chunks.json"
_EPS = 1e-10


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None  # shape (n, d), float32

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must be the same length")
        if not chunks:
            return
        new = np.asarray(vectors, dtype=np.float32)
        self._vectors = new if self._vectors is None else np.vstack([self._vectors, new])
        self._chunks.extend(chunks)

    def search(self, query_vector: list[float], k: int) -> list[Hit]:
        if self._vectors is None or not self._chunks:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) + _EPS)
        mat = self._vectors / (np.linalg.norm(self._vectors, axis=1, keepdims=True) + _EPS)
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [Hit(chunk=self._chunks[i], score=float(scores[i])) for i in top]

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        vectors = self._vectors if self._vectors is not None else np.zeros((0, 0), dtype=np.float32)
        np.save(directory / _VECTORS_FILE, vectors)
        (directory / _CHUNKS_FILE).write_text(
            json.dumps(self._chunks), encoding="utf-8"
        )

    @classmethod
    def load(cls, directory: str | Path) -> "InMemoryVectorStore":
        directory = Path(directory)
        store = cls()
        store._vectors = np.load(directory / _VECTORS_FILE)
        store._chunks = json.loads((directory / _CHUNKS_FILE).read_text(encoding="utf-8"))
        return store
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vectorstore.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/providers/vectorstore.py tests/test_vectorstore.py
git commit -m "feat: add brute-force in-memory vector store with save/load"
```

---

## Task 4: Embeddings provider (`app/providers/embeddings.py`)

Wraps a local sentence-transformers model. Tests inject a fake model so they stay offline and fast.

**Files:**
- Create: `app/providers/embeddings.py`
- Test: `tests/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

`tests/test_embeddings.py`:
```python
import numpy as np

from app.providers.embeddings import SentenceTransformerEmbeddings


class _FakeModel:
    """Stand-in for a SentenceTransformer: .encode returns a numpy array."""

    def encode(self, texts):
        # one 2-d vector per text, deterministic from length
        return np.array([[float(len(t)), 1.0] for t in texts], dtype=np.float32)


def test_embed_returns_one_vector_per_text():
    emb = SentenceTransformerEmbeddings(model=_FakeModel())
    vecs = emb.embed(["a", "bbb"])
    assert len(vecs) == 2
    assert vecs[0] == [1.0, 1.0]
    assert vecs[1] == [3.0, 1.0]


def test_embed_returns_plain_python_floats():
    emb = SentenceTransformerEmbeddings(model=_FakeModel())
    vecs = emb.embed(["x"])
    assert isinstance(vecs, list)
    assert isinstance(vecs[0][0], float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embeddings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.embeddings'`.

- [ ] **Step 3: Write `app/providers/embeddings.py`**

```python
"""Local embeddings via sentence-transformers.

The heavy model import is deferred to construction so importing this module
(e.g. in tests) does not pull in torch. Pass `model=` to inject a fake.
"""
from __future__ import annotations

from typing import Any

import numpy as np

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"


class SentenceTransformerEmbeddings:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, model: Any | None = None) -> None:
        if model is not None:
            self._model = model
        else:
            from sentence_transformers import SentenceTransformer  # lazy, heavy import

            self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts)
        return np.asarray(vectors, dtype=np.float32).tolist()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embeddings.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/providers/embeddings.py tests/test_embeddings.py
git commit -m "feat: add local sentence-transformers embedding provider"
```

---

## ✅ Code-review checkpoint A — retrieval core

The retrieval core (types, chunking, vector store, embeddings) is complete and independently testable.

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (12 so far).

- [ ] **Step 2: Request a code review**

Invoke the `superpowers:requesting-code-review` skill (or run `/code-review`) against the diff since the Task 0 scaffold commit. Focus areas: the chunking line-math/overlap edge cases, the cosine/save-load correctness in the vector store, and adherence to the "no vendor SDK outside providers" rule.

- [ ] **Step 3: Address findings**

Apply fixes (each as its own TDD cycle if behavior changes), re-run `pytest -q`, and commit. Then continue.

---

## Task 5: Ingestion (`app/ingest.py`)

Resolve a source (local dir or git-cloned URL), walk + filter files, chunk + embed + store.

**Files:**
- Create: `app/ingest.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ingest.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingest'`.

- [ ] **Step 3: Write `app/ingest.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/ingest.py tests/test_ingest.py
git commit -m "feat: add ingestion (walk/filter/chunk/embed/store)"
```

---

## Task 6: Retrieval (`app/retrieve.py`)

Embed the question, return top-k hits.

**Files:**
- Create: `app/retrieve.py`
- Test: `tests/test_retrieve.py`

- [ ] **Step 1: Write the failing test**

`tests/test_retrieve.py`:
```python
from app.retrieve import retrieve
from app.providers.vectorstore import InMemoryVectorStore


class _FakeEmbedder:
    def embed(self, texts):
        # "x" -> points along axis 0, anything else -> axis 1
        return [[1.0, 0.0] if t == "x" else [0.0, 1.0] for t in texts]


def _chunk(cid, vec_axis):
    return {"id": cid, "path": "f.py", "start_line": 1, "end_line": 1, "text": cid}


def test_retrieve_embeds_query_and_returns_top_k():
    store = InMemoryVectorStore()
    store.add(
        [_chunk("along-x", 0), _chunk("along-y", 1)],
        [[1.0, 0.0], [0.0, 1.0]],
    )
    hits = retrieve(store, _FakeEmbedder(), "x", k=1)
    assert len(hits) == 1
    assert hits[0]["chunk"]["id"] == "along-x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retrieve.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieve'`.

- [ ] **Step 3: Write `app/retrieve.py`**

```python
"""Retrieval: embed the question and return the top-k most similar chunks."""
from __future__ import annotations

from app.types import EmbeddingProvider, Hit, VectorStore


def retrieve(
    store: VectorStore,
    embedder: EmbeddingProvider,
    question: str,
    k: int = 8,
) -> list[Hit]:
    query_vector = embedder.embed([question])[0]
    return store.search(query_vector, k)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retrieve.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/retrieve.py tests/test_retrieve.py
git commit -m "feat: add retrieval (embed query + top-k search)"
```

---

## Task 7: LLM provider (`app/providers/llm.py`)

Anthropic Claude. Tests inject a fake client so they stay offline.

**Files:**
- Create: `app/providers/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.llm'`.

- [ ] **Step 3: Write `app/providers/llm.py`**

```python
"""Anthropic Claude LLM provider.

Defaults to claude-opus-4-8 (override with the ANTHROPIC_MODEL env var, e.g.
claude-haiku-4-5 for cheaper dev runs). Requires ANTHROPIC_API_KEY in the
environment. Pass `client=` to inject a fake in tests.
"""
from __future__ import annotations

import os
from typing import Any

from app.types import Tokens

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 4096


class AnthropicLLM:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/providers/llm.py tests/test_llm.py
git commit -m "feat: add Anthropic Claude LLM provider with usage capture"
```

---

## Task 8: Grounded generation (`app/generate.py`)

Build the grounded prompt, call the LLM, parse the structured JSON, map block ids to citations.

**Files:**
- Create: `app/generate.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_generate.py`:
```python
from app.generate import build_user_prompt, generate_answer


def _hit(cid, path, s, e, text, score=0.9):
    return {
        "chunk": {"id": cid, "path": path, "start_line": s, "end_line": e, "text": text},
        "score": score,
    }


class _FakeLLM:
    def __init__(self, raw):
        self._raw = raw
        self.last_usage = {"input": 3, "output": 2}

    def generate(self, system, user):
        self.captured = (system, user)
        return self._raw


def test_build_user_prompt_includes_numbered_blocks_and_question():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    prompt = build_user_prompt("where is auth?", hits)
    assert "a.py:1-2" in prompt
    assert "code A" in prompt
    assert "where is auth?" in prompt


def test_generate_answer_maps_used_ids_to_citations():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A"), _hit("b.py:3-4", "b.py", 3, 4, "code B")]
    llm = _FakeLLM('{"answer": "In a.py.", "used_block_ids": ["a.py:1-2"], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["answer"] == "In a.py."
    assert result["refused"] is False
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]
    assert result["tokens"] == {"input": 3, "output": 2}


def test_generate_answer_handles_refusal():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "I don\'t find that in the code.", "used_block_ids": [], "refused": true}')
    result = generate_answer(llm, "unrelated?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_fails_closed_on_bad_json():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM("not json at all")
    result = generate_answer(llm, "where?", hits)
    assert result["refused"] is True
    assert result["citations"] == []


def test_generate_answer_ignores_unknown_block_ids():
    hits = [_hit("a.py:1-2", "a.py", 1, 2, "code A")]
    llm = _FakeLLM('{"answer": "x", "used_block_ids": ["ghost:9-9", "a.py:1-2"], "refused": false}')
    result = generate_answer(llm, "where?", hits)
    assert result["citations"] == [{"path": "a.py", "start_line": 1, "end_line": 2}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.generate'`.

- [ ] **Step 3: Write `app/generate.py`**

```python
"""Grounded answer generation with structured-JSON citations.

The model is given numbered context blocks and must answer ONLY from them,
returning a JSON object {answer, used_block_ids, refused}. We map the returned
block ids back to citations. Malformed JSON is treated as a refusal (fail closed).
"""
from __future__ import annotations

import json

from app.types import Citation, Hit, LLMProvider, Tokens

REFUSAL_TEXT = "I don't find that in the code."

SYSTEM_PROMPT = (
    "You are a code-comprehension assistant. Answer the question using ONLY the "
    "numbered context blocks provided. Do not use outside knowledge. If the blocks "
    "do not contain enough information to answer, you must refuse.\n\n"
    "Respond with a single JSON object and nothing else, in this exact shape:\n"
    '{"answer": "<your answer>", "used_block_ids": ["<id>", ...], "refused": <true|false>}\n'
    'Each id in used_block_ids MUST be copied verbatim from a block header. '
    'If you cannot answer from the blocks, set "refused" to true, set "used_block_ids" to [], '
    f'and set "answer" to "{REFUSAL_TEXT}"'
)


def build_user_prompt(question: str, hits: list[Hit]) -> str:
    lines = ["Context blocks:\n"]
    for hit in hits:
        c = hit["chunk"]
        lines.append(f"[{c['id']}] ({c['path']} lines {c['start_line']}-{c['end_line']})")
        lines.append(c["text"])
        lines.append("")  # blank separator
    lines.append(f"Question: {question}")
    return "\n".join(lines)


def _refusal(tokens: Tokens) -> dict:
    return {"answer": REFUSAL_TEXT, "citations": [], "refused": True, "tokens": tokens}


def generate_answer(llm: LLMProvider, question: str, hits: list[Hit]) -> dict:
    """Return {answer, citations, refused, tokens}. Latency/result-shape wiring
    happens in app.query."""
    user = build_user_prompt(question, hits)
    raw = llm.generate(SYSTEM_PROMPT, user)
    tokens: Tokens = getattr(llm, "last_usage", {"input": 0, "output": 0})

    try:
        parsed = json.loads(raw)
        answer = str(parsed["answer"])
        refused = bool(parsed.get("refused", False))
        used_ids = parsed.get("used_block_ids", []) or []
    except (json.JSONDecodeError, KeyError, TypeError):
        return _refusal(tokens)

    if refused:
        return {"answer": answer, "citations": [], "refused": True, "tokens": tokens}

    by_id = {hit["chunk"]["id"]: hit["chunk"] for hit in hits}
    citations: list[Citation] = []
    for cid in used_ids:
        chunk = by_id.get(cid)
        if chunk is not None:
            citations.append(
                Citation(
                    path=chunk["path"],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                )
            )
    return {"answer": answer, "citations": citations, "refused": False, "tokens": tokens}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/generate.py tests/test_generate.py
git commit -m "feat: add grounded generation with structured-JSON citations"
```

---

## Task 9: Query orchestration (`app/query.py`)

Ties retrieve + generate + timing into the parity result shape.

**Files:**
- Create: `app/query.py`
- Test: `tests/test_query.py`

- [ ] **Step 1: Write the failing test**

`tests/test_query.py`:
```python
from app.query import answer_query
from app.providers.vectorstore import InMemoryVectorStore


class _FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeLLM:
    last_usage = {"input": 4, "output": 6}

    def generate(self, system, user):
        return '{"answer": "A.", "used_block_ids": ["f.py:1-1"], "refused": false}'


def test_answer_query_returns_full_result_shape():
    store = InMemoryVectorStore()
    store.add(
        [{"id": "f.py:1-1", "path": "f.py", "start_line": 1, "end_line": 1, "text": "code"}],
        [[1.0, 0.0]],
    )
    result = answer_query(store, _FakeEmbedder(), _FakeLLM(), "where?", k=3)
    assert result["answer"] == "A."
    assert result["refused"] is False
    assert result["citations"] == [{"path": "f.py", "start_line": 1, "end_line": 1}]
    assert result["tokens"] == {"input": 4, "output": 6}
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_query.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.query'`.

- [ ] **Step 3: Write `app/query.py`**

```python
"""Query orchestration: retrieve -> generate -> timed parity result.

Returns the same shape the Phase 1 POST /query endpoint will return, so Phase 1
can wrap this function with no reshaping.
"""
from __future__ import annotations

import time

from app.generate import generate_answer
from app.retrieve import retrieve
from app.types import EmbeddingProvider, LLMProvider, QueryResult, VectorStore


def answer_query(
    store: VectorStore,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    question: str,
    k: int = 8,
) -> QueryResult:
    started = time.perf_counter()
    hits = retrieve(store, embedder, question, k)
    generated = generate_answer(llm, question, hits)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "answer": generated["answer"],
        "citations": generated["citations"],
        "refused": generated["refused"],
        "latency_ms": latency_ms,
        "tokens": generated["tokens"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_query.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```powershell
git add app/query.py tests/test_query.py
git commit -m "feat: add query orchestration with parity result shape"
```

---

## ✅ Code-review checkpoint B — generation path

The full query path (ingest → retrieve → generate → query) is complete.

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (~23).

- [ ] **Step 2: Request a code review**

Invoke `superpowers:requesting-code-review` (or `/code-review`) on the diff since checkpoint A. Focus: the grounding contract robustness in `generate.py` (refusal + malformed-JSON + unknown-id paths), the LLM request construction, and that observability fields (tokens, latency) thread through correctly.

- [ ] **Step 3: Address findings**, re-run `pytest -q`, commit, then continue.

---

## Task 10: CLI (`cli.py`)

`rag ingest` and `rag query` subcommands wiring the real providers together.

**Files:**
- Create: `cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

This test exercises argument parsing without touching the network or heavy models, by checking the parser shape. `cli.py` keeps provider construction inside the command functions so importing it is cheap.

`tests/test_cli.py`:
```python
from cli import build_parser


def test_parser_has_ingest_and_query_subcommands():
    parser = build_parser()
    ns = parser.parse_args(["ingest", "--path", "."])
    assert ns.command == "ingest"
    assert ns.path == "."
    assert ns.out == "index"
    assert ns.window == 60
    assert ns.overlap == 15

    ns2 = parser.parse_args(["query", "where is auth?", "-k", "5"])
    assert ns2.command == "query"
    assert ns2.question == "where is auth?"
    assert ns2.k == 5
    assert ns2.index == "index"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli'`.

- [ ] **Step 3: Write `cli.py`**

```python
"""Phase 0 CLI: ingest a repo, then ask cited questions about it.

  rag ingest --path .            # build the index from a local dir
  rag ingest --repo-url <URL>    # build the index from a cloned public repo
  rag query "where does X?"      # answer a question with citations
"""
from __future__ import annotations

import argparse
import json
import sys

from app.chunk import DEFAULT_OVERLAP, DEFAULT_WINDOW


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="Local RAG over a codebase.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Build the index from a repo.")
    src = p_ingest.add_mutually_exclusive_group(required=True)
    src.add_argument("--path", help="Local directory to index.")
    src.add_argument("--repo-url", dest="repo_url", help="Public git URL to clone and index.")
    p_ingest.add_argument("--out", default="index", help="Output index directory (default: index).")
    p_ingest.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    p_ingest.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)

    p_query = sub.add_parser("query", help="Ask a question about the indexed repo.")
    p_query.add_argument("question", help="The natural-language question.")
    p_query.add_argument("--index", default="index", help="Index directory (default: index).")
    p_query.add_argument("-k", type=int, default=8, help="Top-k chunks to retrieve.")

    return parser


def _cmd_ingest(ns: argparse.Namespace) -> int:
    from app.ingest import build_index, resolve_source
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.vectorstore import InMemoryVectorStore

    root = resolve_source(path=ns.path, repo_url=ns.repo_url)
    embedder = SentenceTransformerEmbeddings()
    store = InMemoryVectorStore()
    n = build_index(root, embedder, store, window=ns.window, overlap=ns.overlap)
    store.save(ns.out)
    print(f"Indexed {n} chunks from {root} -> {ns.out}/")
    return 0


def _cmd_query(ns: argparse.Namespace) -> int:
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.llm import AnthropicLLM
    from app.providers.vectorstore import InMemoryVectorStore
    from app.query import answer_query

    store = InMemoryVectorStore.load(ns.index)
    embedder = SentenceTransformerEmbeddings()
    llm = AnthropicLLM()
    result = answer_query(store, embedder, llm, ns.question, k=ns.k)

    print(result["answer"])
    print()
    if result["citations"]:
        print("Citations:")
        for c in result["citations"]:
            print(f"  - {c['path']}:{c['start_line']}-{c['end_line']}")
    else:
        print("Citations: (none)")
    print()
    print(
        f"[latency={result['latency_ms']}ms "
        f"tokens in/out={result['tokens']['input']}/{result['tokens']['output']} "
        f"refused={result['refused']}]"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "ingest":
        return _cmd_ingest(ns)
    if ns.command == "query":
        return _cmd_query(ns)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Real end-to-end smoke test (manual)**

This is the Phase 0 exit criterion in miniature. Requires `ANTHROPIC_API_KEY` set and downloads the embedding model on first run.

Set the key (PowerShell): `$env:ANTHROPIC_API_KEY = "sk-ant-..."`
(Bash: `export ANTHROPIC_API_KEY=sk-ant-...`)

Run:
```powershell
rag ingest --path .
rag query "Where does line-based chunking happen and how is overlap handled?"
```
Expected: a grounded answer that cites `app/chunk.py` with a line range, plus a latency/token line. If you ask something unrelated (e.g. `rag query "What is the capital of France?"`), it should refuse with "I don't find that in the code."

> Tip for cheaper iteration: `$env:ANTHROPIC_MODEL = "claude-haiku-4-5"` before `rag query`.

- [ ] **Step 6: Commit**

```powershell
git add cli.py tests/test_cli.py
git commit -m "feat: add ingest/query CLI"
```

---

## Task 11: Eval harness (`eval/golden.yaml` + `eval/run_eval.py`)

A golden question set about THIS repo and a scorer that prints retrieval hit-rate + answer correctness.

**Files:**
- Create: `eval/golden.yaml`
- Create: `eval/run_eval.py`
- Test: `tests/test_run_eval.py`

- [ ] **Step 1: Write the failing test**

`tests/test_run_eval.py`:
```python
from eval.run_eval import score_question


def _result(answer, citations, refused=False):
    return {
        "answer": answer,
        "citations": citations,
        "refused": refused,
        "latency_ms": 1,
        "tokens": {"input": 0, "output": 0},
    }


def test_retrieval_hit_when_expected_file_is_cited():
    result = _result("Chunking lives in app/chunk.py.", [{"path": "app/chunk.py", "start_line": 1, "end_line": 60}])
    score = score_question(
        result,
        expected_files=["app/chunk.py"],
        expected_keywords=["chunk"],
    )
    assert score["retrieval_hit"] is True
    assert score["answer_correct"] is True


def test_retrieval_miss_and_keyword_miss():
    result = _result("Something unrelated.", [{"path": "app/other.py", "start_line": 1, "end_line": 2}])
    score = score_question(result, expected_files=["app/chunk.py"], expected_keywords=["chunk"])
    assert score["retrieval_hit"] is False
    assert score["answer_correct"] is False


def test_refusal_on_answerable_question_is_a_miss():
    result = _result("I don't find that in the code.", [], refused=True)
    score = score_question(result, expected_files=["app/chunk.py"], expected_keywords=["chunk"])
    assert score["answer_correct"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_eval.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.run_eval'`.

- [ ] **Step 3: Write `eval/golden.yaml`**

Author 6 questions about this repo's own code. (These reference modules that exist by the time ingest runs.)

```yaml
# Golden question set for the Serverless-Rag repo itself.
# Each item: a question, the file(s) we expect retrieval to surface, and
# keywords the answer should contain (case-insensitive substring match).
- question: "Where does line-based chunking happen and how is overlap handled?"
  expected_files: ["app/chunk.py"]
  expected_keywords: ["overlap", "window"]

- question: "How are vectors searched? What similarity does the vector store use?"
  expected_files: ["app/providers/vectorstore.py"]
  expected_keywords: ["cosine"]

- question: "Which embedding model is used by default?"
  expected_files: ["app/providers/embeddings.py"]
  expected_keywords: ["MiniLM"]

- question: "How does ingestion decide which files to skip?"
  expected_files: ["app/ingest.py"]
  expected_keywords: ["node_modules"]

- question: "What is the grounding contract the LLM must return?"
  expected_files: ["app/generate.py"]
  expected_keywords: ["used_block_ids", "refused"]

- question: "Which Claude model does the LLM provider default to?"
  expected_files: ["app/providers/llm.py"]
  expected_keywords: ["claude-opus-4-8"]
```

- [ ] **Step 4: Write `eval/run_eval.py`**

```python
"""Eval harness: run the golden questions through the query path and score.

  python -m eval.run_eval --index index --golden eval/golden.yaml

Scoring (deterministic, cheap):
  - retrieval hit-rate: did an expected file appear among the citations?
  - answer correctness: all expected keywords present (case-insensitive) and
    not a refusal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from app.types import QueryResult


def score_question(
    result: QueryResult, expected_files: list[str], expected_keywords: list[str]
) -> dict:
    cited_paths = {c["path"] for c in result["citations"]}
    retrieval_hit = any(f in cited_paths for f in expected_files)

    answer_lower = result["answer"].lower()
    keywords_present = all(kw.lower() in answer_lower for kw in expected_keywords)
    answer_correct = (not result["refused"]) and keywords_present

    return {"retrieval_hit": retrieval_hit, "answer_correct": answer_correct}


def _run(index_dir: str, golden_path: str) -> int:
    from app.providers.embeddings import SentenceTransformerEmbeddings
    from app.providers.llm import AnthropicLLM
    from app.providers.vectorstore import InMemoryVectorStore
    from app.query import answer_query

    golden = yaml.safe_load(Path(golden_path).read_text(encoding="utf-8"))
    store = InMemoryVectorStore.load(index_dir)
    embedder = SentenceTransformerEmbeddings()
    llm = AnthropicLLM()

    rows = []
    hits = correct = 0
    for item in golden:
        result = answer_query(store, embedder, llm, item["question"], k=8)
        score = score_question(result, item["expected_files"], item["expected_keywords"])
        hits += int(score["retrieval_hit"])
        correct += int(score["answer_correct"])
        rows.append((item["question"], score))
        flag = "HIT " if score["retrieval_hit"] else "miss"
        ans = "OK  " if score["answer_correct"] else "bad "
        print(f"[retrieval {flag}] [answer {ans}] {item['question']}")

    n = len(golden)
    print()
    print(f"Retrieval hit-rate : {hits}/{n} = {hits / n:.0%}")
    print(f"Answer correctness : {correct}/{n} = {correct / n:.0%}")

    results_dir = Path("eval/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "latest.json").write_text(
        json.dumps(
            {"n": n, "retrieval_hits": hits, "answers_correct": correct},
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--index", default="index")
    parser.add_argument("--golden", default="eval/golden.yaml")
    ns = parser.parse_args(argv)
    return _run(ns.index, ns.golden)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_run_eval.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the real eval (manual)**

Requires `ANTHROPIC_API_KEY` and an index built from Task 10's smoke test (`rag ingest --path .`).

Run: `python -m eval.run_eval`
Expected: a per-question table and two summary percentages, plus `eval/results/latest.json` written. The first eval score is the Phase 0 headline number — record it.

- [ ] **Step 7: Commit**

```powershell
git add eval/golden.yaml eval/run_eval.py tests/test_run_eval.py
git commit -m "feat: add golden set and eval harness (hit-rate + correctness)"
```

---

## Task 12: README + final verification

**Files:**
- Create/Modify: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Serverless-Rag — Phase 0 (local RAG proof)

Point it at a code repository, then ask natural-language questions and get
answers grounded in the actual code, cited to exact files and line ranges.

This is Phase 0: a local CLI + eval harness, no AWS. See
[`docs/PROJECT.md`](docs/PROJECT.md) for the full plan and later phases.

## Setup

Requires Python 3.11+ and an Anthropic API key.

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1   | Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...   # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

First run downloads the `all-MiniLM-L6-v2` embedding model and (via
sentence-transformers) `torch` — a large one-time install.

## 60-second demo

```bash
rag ingest --path .                       # build the index from this repo
rag query "Where does chunking happen?"   # grounded, cited answer
python -m eval.run_eval                    # score the golden set
```

Set `ANTHROPIC_MODEL=claude-haiku-4-5` for cheaper iteration; the default is
`claude-opus-4-8`.

## How it works

- **Ingest:** walk + filter files → line-based chunks (path + line range) →
  local embeddings → `index/vectors.npy` + `index/chunks.json`.
- **Query:** embed the question → brute-force cosine top-k → grounded prompt →
  Claude returns `{answer, used_block_ids, refused}` → mapped to citations.
- **Eval:** golden Q/A in `eval/golden.yaml`, scored for retrieval hit-rate and
  answer correctness.

Embeddings, vector store, and LLM are each pluggable behind one Protocol
(`app/types.py`) — swapping a vendor touches no query/ingest logic.

## Current eval score

_Fill in after running `python -m eval.run_eval` (e.g. retrieval 6/6, answers 5/6)._
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass (~27).

- [ ] **Step 3: Fill in the real eval score** in the README's "Current eval score" section using `eval/results/latest.json` from Task 11.

- [ ] **Step 4: Commit**

```powershell
git add README.md
git commit -m "docs: add Phase 0 README with setup, demo, and eval score"
```

---

## ✅ Code-review checkpoint C — final review

- [ ] **Step 1: Confirm the full suite passes**

Run: `pytest -q`
Expected: all green. Capture the count.

- [ ] **Step 2: Verify the exit criterion with evidence**

Use `superpowers:verification-before-completion`. The Phase 0 exit criterion (PROJECT.md) is: *cited answers from the terminal + a first eval score.* Confirm with real output:
- `rag query "..."` produced a correct, cited answer (paste it).
- `python -m eval.run_eval` produced a number (paste the two percentages).

- [ ] **Step 3: Request a final code review**

Invoke `superpowers:requesting-code-review` (or `/code-review`) on the whole Phase 0 diff. Address findings.

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch` to decide how to integrate (merge / PR / cleanup).

---

## Self-review (plan author)

- **Spec coverage:** scope/no-AWS (Tasks 0, 12) ✓; module layout (Tasks 1–11) ✓; provider decisions — Claude LLM (Task 7), local embeddings (Task 4), brute-force store (Task 3), this repo as target (Task 11 golden set) ✓; line-based chunking 60/15 (Task 2) ✓; on-disk format vectors.npy+chunks.json (Task 3) ✓; structured-JSON grounding contract (Task 8) ✓; parity result shape (Task 9) ✓; data flow ingest/query/eval (Tasks 5, 9, 11) ✓; testing strategy — provider + chunker + generate JSON contract unit tests, eval as integration (every task + Task 11) ✓; observability latency/tokens (Tasks 7, 9, 10) ✓; AWS deferred (Task 0/12 notes) ✓.
- **Added beyond spec layout:** `app/query.py` (Task 9) to host the timed parity result shape the spec's §5.5 describes — small, justified, keeps Phase 1 wrapping trivial. Noted here so it's intentional, not drift.
- **Placeholder scan:** the only intentional placeholder is the README "Current eval score" line, filled in Task 12 Step 3 from real output. No TBDs in code.
- **Type consistency:** `Chunk`/`Hit`/`Citation`/`Tokens`/`QueryResult` defined in Task 1 and used unchanged throughout; `build_index`, `chunk_file`, `retrieve`, `generate_answer`, `answer_query`, `score_question` signatures match across their definition and call sites; `last_usage`/`Tokens` shape consistent between `llm.py`, `generate.py`, `query.py`.
