from app.render.tts import speakable


def test_code_tables_links_and_markup_are_dropped():
    md = ("# Итог\n\nПравка **готова**, смотри `main.py`.\n\n```python\nprint(1)\n```\n\n"
          "| a | b |\n|---|---|\n| 1 | 2 |\n\n- пункт один\n- [докs](https://x.y/z)\n\nСсылка https://a.b/c и <b>тег</b>.")
    assert speakable(md) == "Итог\nПравка готова, смотри .\nпункт один\nдокs\nСсылка и тег."


def test_cut_at_a_sentence_boundary_within_the_limit():
    text = "Первое предложение. Второе предложение! Третье очень длинное предложение без конца"
    assert speakable(text, limit=45) == "Первое предложение. Второе предложение!"
    assert speakable(text, limit=1000) == text


def test_empty_when_only_code():
    assert speakable("```\nx = 1\n```") == ""
