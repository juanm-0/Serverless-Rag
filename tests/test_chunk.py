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
    # window (which would be 136-150, a strict subset of 91-150) is emitted.
    assert [(c["start_line"], c["end_line"]) for c in chunks] == [
        (1, 60),
        (46, 105),
        (91, 150),
    ]
    # ids are derived from the line range
    assert chunks[0]["id"] == "big.py:1-60"
    # overlap is real: line 46 appears in both chunk 0 and chunk 1
    assert "L46" in chunks[0]["text"]
    assert "L46" in chunks[1]["text"]
    # every line is covered by at least one chunk
    assert "L150" in chunks[-1]["text"]


def test_trailing_window_emitted_only_when_it_adds_new_lines():
    text = "\n".join(f"L{i}" for i in range(1, 161))  # 160 lines
    chunks = chunk_file("big.py", text, window=60, overlap=15)
    # Here the 4th window (136-160) extends past the 3rd (91-150), so it is
    # kept — it adds lines 151-160.
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
