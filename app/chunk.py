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

    # A file that fits within a single window is one chunk spanning the whole
    # file. Otherwise slide the window forward by `step`, emitting a (clamped)
    # window at every start position that begins before the end of the file.
    starts = [0] if n <= window else list(range(0, n, step))
    for start in starts:
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
    return chunks
