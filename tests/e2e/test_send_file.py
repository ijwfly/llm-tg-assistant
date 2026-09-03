from pathlib import Path

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text, wait_turn_finished
from tests.support.updates import text_update

LONG = "Файл отправлен, смотри выше, вот ещё достаточно длинный текст, чтобы он ушёл в чат сразу одним сообщением. " * 2


async def test_send_file_delivers_a_photo_and_a_document(app, spy, fake_claude, tmp_path):
    work = Path(settings.DEFAULT_CWD)
    (work / "chart.png").write_bytes(b"\x89PNG fake")
    (work / "out").mkdir()
    (work / "out" / "report.md").write_text("# Отчёт\n")
    fake_claude.enqueue(fc.mcp_tool("send_file", {"path": "chart.png", "caption": "график"}),
                        fc.mcp_tool("send_file", {"path": str(work / "out" / "report.md")}),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("пришли график и отчёт"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    photo = spy.calls("SendPhoto")[-1]
    assert photo["photo"].endswith("chart.png") and photo["caption"] == "график" and photo["chat_id"] == 1
    doc = spy.calls("SendDocument")[-1]
    assert doc["document"].endswith("report.md") and "caption" not in doc
    results = fake_claude.mcp_results()
    assert results[0] == {"text": "File chart.png (9 B) sent to the chat.", "is_error": False, "error": None}
    assert results[1]["text"] == "File report.md (13 B) sent to the chat."
    order = [n for n, _ in spy.session.calls if n in ("SendPhoto", "SendDocument", "SendRichMessage")]
    assert order == ["SendPhoto", "SendDocument", "SendRichMessage"]


async def test_send_file_refuses_bad_paths(app, spy, fake_claude, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    fake_claude.enqueue(fc.mcp_tool("send_file", {"path": str(outside)}),
                        fc.mcp_tool("send_file", {"path": "missing.txt"}),
                        fc.mcp_tool("send_file", {"path": ""}),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("пришли"))
    await wait_turn_finished(app)
    results = fake_claude.mcp_results()
    assert [r["is_error"] for r in results] == [True, True, True]
    assert results[0]["text"].endswith("is outside the allowed directories.")
    assert results[1]["text"].endswith("is not a file.")
    assert results[2]["text"] == "Error: path is required."
    assert spy.calls("SendDocument") == [] and spy.calls("SendPhoto") == []


async def test_send_file_tool_is_absent_when_disabled(app, spy, fake_claude):
    settings.BRIDGE_SEND_FILE_TOOL = False
    fake_claude.enqueue(fc.mcp_tool("list"), fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("что умеешь?"))
    await wait_turn_finished(app)
    assert fake_claude.mcp_tools() == [["approve"]]


async def test_send_file_tool_is_listed_and_permission_is_granted_without_a_card(app, spy, fake_claude):
    work = Path(settings.DEFAULT_CWD)
    (work / "a.txt").write_text("x")
    fake_claude.enqueue(fc.mcp_tool("list"),
                        fc.prompt_tool("mcp__tgbridge__send_file", {"path": "a.txt"}),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("пришли a.txt"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    assert fake_claude.mcp_tools() == [["approve", "send_file"]]
    assert fake_claude.decisions() == [{"behavior": "allow", "updatedInput": {"path": "a.txt"}}]
    assert not any("просит разрешение" in t for t in spy.sent_texts())
    assert await app.db.fetchval("SELECT count(*) FROM pending_prompts") == 0
