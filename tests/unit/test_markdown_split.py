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
