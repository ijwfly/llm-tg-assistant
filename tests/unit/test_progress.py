import random

from app.render.progress import PHRASES, ProgressState, draft_markdown, progress_text, tool_detail


def test_tool_details_are_short_and_safe():
    assert tool_detail("Read", {"file_path": "/a/" + "b" * 80 + "/main.py"}).startswith("…") and \
        tool_detail("Read", {"file_path": "/a/" + "b" * 80 + "/main.py"}).endswith("main.py")
    assert tool_detail("Bash", {"command": "cargo test --workspace " + "x" * 80}).endswith("…")
    assert tool_detail("Bash", {"command": "git status\nrm -rf /"}) == "git status"
    assert tool_detail("Grep", {"pattern": "def main"}) == "def main"
    assert tool_detail("mcp__github__create_issue", {"token": "secret"}) is None
    assert tool_detail("WebFetch", {"url": "https://example.com/x"}) == "https://example.com/x"


def test_progress_line_has_phrase_trail_count_and_clock():
    st = ProgressState(started=100.0)
    st.add_tool("Grep", {"pattern": "x"}, subagent=False)
    st.add_tool("Read", {"file_path": "src/main.rs"}, subagent=False)
    line = st.line(now=172.0, rnd=random.Random(1))
    assert line.endswith("(2 · 1:12)")
    assert "Grep → Read src/main.rs" in line
    assert any(line.startswith(p) for p in PHRASES[1][1])  # 72 s -> second bucket


def test_trail_keeps_last_three_and_marks_subagents():
    st = ProgressState(started=0.0)
    for name in ("Glob", "Grep", "Read", "Bash"):
        st.add_tool(name, {}, subagent=False)
    st.add_tool("Grep", {"pattern": "y"}, subagent=True)
    assert st.trail == ["Read", "Bash", "Task ▸ Grep"]


def test_phrase_is_stable_within_a_bucket_and_changes_on_transition():
    st = ProgressState(started=0.0)
    a = st.line(now=1.0, rnd=random.Random(3)).split(" (")[0]
    b = st.line(now=10.0, rnd=random.Random(4)).split(" (")[0]
    assert a == b
    c = st.line(now=30.0, rnd=random.Random(5)).split(" (")[0]
    assert c != a and any(c.startswith(p) for p in PHRASES[1][1])


def test_waiting_state_replaces_phrase():
    st = ProgressState(started=0.0)
    st.waiting = "🔐 жду разрешения (Bash)"
    assert st.line(now=5.0).startswith("🔐 жду разрешения (Bash) (0 · 0:05)")


def test_draft_and_progress_rendering():
    md = draft_markdown("копаю ⛏️ (1 · 0:05)", "Проверяю фикстуру", "Текст ответа " * 10, show_thinking=True, frozen_limit=50)
    assert md.startswith("<tg-thinking>копаю ⛏️ (1 · 0:05)\n🧠 Проверяю фикстуру</tg-thinking>\n")
    assert md.endswith(" ⏳…")
    assert "🧠" not in draft_markdown("x", "y", "", show_thinking=False, frozen_limit=10)
    assert progress_text("копаю", "короткий", preview_chars=600, show_preview=True) == "копаю"
    long = "слово " * 30
    assert progress_text("копаю", long, preview_chars=600, show_preview=True).startswith("копаю\n—\n")
    assert progress_text("копаю", long, preview_chars=600, show_preview=False) == "копаю"
