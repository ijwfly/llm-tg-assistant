from pathlib import Path

import settings
from app.render.cards import diff_block, fence, mask_secrets, option_label, permission_card, plan_card, question_card


def test_bash_card_has_command_fence_and_description():
    md = permission_card("Bash", {"command": "ls -la", "description": "посмотреть"})
    assert md == "🔐 **Bash** просит разрешение\n```bash\nls -la\n```\n_посмотреть_"


def test_fence_grows_when_the_body_contains_backticks():
    assert fence("a\n```\nb", "md").startswith("````md\n")


def test_edit_card_renders_a_diff_and_cuts_long_ones():
    settings.PERMISSION_DIFF_LINES = 8   # 2 header lines + hunk header + 5 diff lines
    old = "\n".join(f"line {i}" for i in range(30))
    new = old.replace("line 3", "LINE 3").replace("line 25", "LINE 25")
    md = permission_card("Edit", {"file_path": "/work/p/a.py", "old_string": old, "new_string": new}, cwd="/work/p")
    assert md.startswith("🔐 **Edit** просит разрешение\n`a.py`\n```diff\n")
    assert "-line 3" in md and "+LINE 3" in md and "… ещё" in md and "LINE 25" not in md


def test_write_card_diffs_against_an_existing_file(tmp_path: Path):
    target = tmp_path / "x.txt"
    target.write_text("old\n")
    md = permission_card("Write", {"file_path": str(target), "content": "new\n"})
    assert "(перезапись, 4 B)" in md and "-old" in md and "+new" in md


def test_write_card_shows_the_head_of_a_new_file():
    content = "\n".join(f"l{i}" for i in range(50))
    md = permission_card("Write", {"file_path": "/w/b.rs", "content": content})
    assert "(новый файл" in md and "```rust\n" in md and "l39" in md and "l40" not in md and "… ещё 10 строк" in md


def test_read_like_and_web_cards_are_one_line():
    assert permission_card("Read", {"file_path": "/w/p/a.py"}, cwd="/w/p") == "🔐 **Read** просит разрешение\n`a.py`"
    assert permission_card("Grep", {"pattern": "TODO", "path": "/w/p/src"}, cwd="/w/p").endswith("`TODO` в `src`")
    assert permission_card("WebFetch", {"url": "https://x.y/z"}).endswith("https://x.y/z")
    assert permission_card("WebSearch", {"query": "aiogram drafts"}).endswith("«aiogram drafts»")


def test_unknown_tool_card_masks_secrets_and_cuts_json():
    md = permission_card("mcp__x__y", {"api_key": "abc", "nested": {"password": "p", "ok": "v"}, "big": "z" * 2000})
    assert "abc" not in md and '"api_key": "•••"' in md and '"password": "•••"' in md and '"ok": "v"' in md
    assert md.endswith("…\n```")
    assert mask_secrets({"Authorization": "Bearer x", "count": 3}) == {"Authorization": "•••", "count": 3}


def test_question_and_plan_cards():
    q = {"question": "Какой формат?", "header": "Формат", "multiSelect": True, "options": []}
    assert question_card(q, 0, 2) == "❓ Формат (1/2)\nКакой формат?\n_(можно выбрать несколько)_"
    assert question_card({"question": "Да?", "header": "Ок"}, 0, 1) == "❓ Ок\nДа?"
    assert option_label({"label": "Summary", "description": "кратко"}) == "Summary — кратко"
    assert len(option_label({"label": "x" * 100})) == 60
    assert plan_card("# План\n1. шаг").startswith("📋 **План готов**\n\n# План")


def test_diff_block_default_limit_comes_from_settings():
    settings.PERMISSION_DIFF_LINES = 3
    assert "… ещё" in diff_block("a\nb\nc\nd", "A\nB\nC\nD", "f")
