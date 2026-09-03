from app.render.markdown import format_duration, split_text


def test_split_keeps_lines_together_under_the_limit():
    text = "\n".join(f"line {i}" for i in range(10))
    chunks = split_text(text, 30)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")
    assert all(len(c) <= 30 for c in chunks)
    assert chunks[0] == "line 0\nline 1\nline 2\nline 3"


def test_split_hard_cuts_an_overlong_line():
    chunks = split_text("x" * 25, 10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]


def test_split_empty_text_gives_no_chunks():
    assert split_text("", 10) == []


def test_format_duration():
    assert format_duration(None) == "0 с"
    assert format_duration(5000) == "5 с"
    assert format_duration(72000) == "1 м 12 с"


from app.render.markdown import preview_tail, split_markdown


def test_split_markdown_keeps_short_text_whole():
    assert split_markdown("hello", 100) == ["hello"]


def test_split_markdown_closes_and_reopens_code_fences():
    code = "\n".join(f"line {i}" for i in range(30))
    text = "intro\n\n```python\n" + code + "\n```\n\noutro"
    chunks = split_markdown(text, 120)
    assert len(chunks) >= 2
    for chunk in chunks[:-1]:
        assert chunk.count("```") % 2 == 0, chunk
    assert chunks[1].startswith("```python\n")
    assert "".join(chunks).count("outro") == 1


def test_split_markdown_prefers_paragraph_boundaries():
    text = "para one " * 10 + "\n\n" + "para two " * 10
    chunks = split_markdown(text, 120)
    assert chunks[0].strip().endswith("para one") and chunks[1].startswith("para two")


def test_split_markdown_does_not_cut_a_table_block():
    table = "\n".join(f"| a{i} | b{i} |" for i in range(12))
    text = "before " * 5 + "\n\n" + "| h | h |\n|---|---|\n" + table
    chunks = split_markdown(text, 200)   # the cut would land inside the table; it moves before it
    assert len(chunks) == 2 and chunks[1].startswith("| h | h |") and chunks[1].count("\n") == 13


def test_preview_tail_rules():
    assert preview_tail("short text", 600) == ""
    text = "word " * 20 + "unfinishe"
    assert preview_tail(text, 600).endswith("word") and "unfinishe" not in preview_tail(text, 600)
    long = "x" * 100 + " " + "y" * 100 + " end"
    assert preview_tail(long, 50).startswith("…") and len(preview_tail(long, 50)) == 51
