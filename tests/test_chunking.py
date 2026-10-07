from footy_quiz.hints.chunking import chunk_text


def test_strips_heading_lines():
    text = "== Early life ==\nHe was born in a city. He grew up playing street football."
    chunks = chunk_text(text)
    assert not any("==" in c for c in chunks)
    assert any("born in a city" in c for c in chunks)


def test_merges_short_leading_fragment_forward():
    # A very short first sentence should merge with the next rather than stand alone.
    text = "He retired. After a long and decorated career spanning two decades in Europe."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert "He retired" in chunks[0]
    assert "decorated career" in chunks[0]


def test_caps_chunks_at_two_sentences():
    text = " ".join(f"This is sentence number {i} in a long biography." for i in range(6))
    chunks = chunk_text(text)
    for chunk in chunks:
        # at most 2 sentences worth -- rough proxy: shouldn't contain 3+ "sentence number"s
        assert chunk.count("sentence number") <= 2


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_heading_only_text_returns_no_chunks():
    assert chunk_text("== Career ==\n=== Barcelona ===") == []
