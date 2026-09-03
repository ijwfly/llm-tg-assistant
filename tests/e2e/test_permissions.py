import asyncio
import json
from pathlib import Path

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Сделано: команда выполнена, вот результат, достаточно длинный, чтобы уйти в чат сразу одним сообщением. " * 2


def buttons(payload) -> list[str]:
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def button_texts(payload) -> list[str]:
    return [b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def wait_card(spy, fragment="просит разрешение", timeout=3.0) -> dict:
    """The rich prompt card with its keyboard (the last one containing `fragment`)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for p in reversed(spy.calls("SendRichMessage")):
            if fragment in p["rich_message"]["markdown"] and p.get("reply_markup"):
                return p
        await asyncio.sleep(0.02)
    raise AssertionError(f"no card with {fragment!r}; shown: {spy.sent_texts()!r}")


async def card_message_id(app) -> int:
    for _ in range(100):
        mid = await app.db.fetchval(
            "SELECT delivered_message_id FROM outbox WHERE role = 'prompt' AND status = 'delivered' ORDER BY id DESC LIMIT 1")
        if mid:
            return mid
        await asyncio.sleep(0.02)
    raise AssertionError("card never delivered")


def bash_turn(fake, command="cargo test --workspace", description="Проверить тесты"):
    fake.enqueue(fc.tool_use("Bash", {"command": command, "description": description}),
                 fc.prompt_tool("Bash", {"command": command, "description": description}),
                 fc.tool_result(), fc.assistant_text(LONG), fc.result())


async def test_bash_request_shows_a_card_and_allow_returns_updated_input(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    card = await wait_card(spy)
    md = card["rich_message"]["markdown"]
    assert md.startswith("🔐 **Bash** просит разрешение") and "```bash\ncargo test --workspace\n```" in md
    assert "_Проверить тесты_" in md
    assert buttons(card) == ["pa:1:1", "pd:1:1", "pw:1:1", "pc:1:1"]
    assert button_texts(card)[2] == "Всегда: Bash(cargo test *)"
    assert fake_claude.decisions() == []          # the fake is blocked on the socket
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--permission-prompt-tool") + 1] == "mcp__tgbridge__approve"
    cfg = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["tgbridge"]
    assert cfg["args"][0].endswith("app/bridge/mcp_server.py") and cfg["env"]["TGBRIDGE_SOCKET"] == settings.BRIDGE_SOCKET
    mid = await card_message_id(app)
    await feed(app, callback_update("pa:1:1", message_id=mid))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions() == [{"behavior": "allow", "updatedInput": {"command": "cargo test --workspace",
                                                                               "description": "Проверить тесты"}}]
    await wait_turn_finished(app)
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == mid and edit["rich_message"]["markdown"].endswith("✅ разрешено")
    assert "reply_markup" not in edit
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Разрешено"
    row = await app.db.fetchrow("SELECT * FROM pending_prompts")
    assert row["status"] == "answered" and row["kind"] == "permission" and row["answer"]["behavior"] == "allow"


async def test_deny_button_returns_a_deny_with_a_message(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    await feed(app, callback_update("pd:1:1", message_id=await card_message_id(app)))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions() == [{"behavior": "deny", "message": "User denied this action via Telegram."}]
    await wait_turn_finished(app)
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("❌ отказано")


async def test_always_button_adds_a_local_rule_and_remembers_it(app, spy, fake_claude):
    bash_turn(fake_claude, command="git status")
    await feed(app, text_update("что в гите?"))
    card = await wait_card(spy)
    assert button_texts(card)[2] == "Всегда: Bash(git status *)"
    await feed(app, callback_update("pw:1:1", message_id=await card_message_id(app)))
    await wait_for_text(spy, LONG.strip())
    decision = fake_claude.decisions()[0]
    assert decision["behavior"] == "allow"
    assert decision["updatedPermissions"] == [{"type": "addRules", "behavior": "allow", "destination": "localSettings",
                                               "rules": [{"toolName": "Bash", "ruleContent": "git status *"}]}]
    await wait_turn_finished(app)
    assert await app.db.fetchval("SELECT rule FROM topic_rules") == "Bash(git status *)"
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith(
        "🔓 разрешено, и больше не спрошу: Bash(git status *)")
    await run(app, text_update("/perm"))
    assert "• Bash(git status *)" in spy.last_text()


async def test_no_always_button_for_edits_and_dangerous_commands(app, spy, fake_claude):
    fake_claude.enqueue(fc.prompt_tool("Edit", {"file_path": "/work/a.py", "old_string": "a = 1", "new_string": "a = 2"}),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("поправь"))
    card = await wait_card(spy)
    md = card["rich_message"]["markdown"]
    assert "```diff" in md and "-a = 1" in md and "+a = 2" in md
    assert buttons(card) == ["pa:1:1", "pd:1:1", "pc:1:1"]
    await feed(app, callback_update("pa:1:1", message_id=await card_message_id(app)))
    await wait_turn_finished(app)


async def test_deny_with_comment_uses_the_next_message_and_does_not_start_a_turn(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    await feed(app, callback_update("pc:1:1", message_id=await card_message_id(app)))
    await wait_for_text(spy, "✏️ Напиши следующим сообщением")
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Жду твоё сообщение"
    await feed(app, text_update("только юнит-тесты, без интеграционных"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.decisions() == [{"behavior": "deny", "message": "User denied: только юнит-тесты, без интеграционных"}]
    await wait_turn_finished(app)
    assert fake_claude.stdin_texts() == ["прогони тесты"]        # the comment was not a turn
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith(
        "❌ отказано: «только юнит-тесты, без интеграционных»")


async def test_unanswered_card_times_out_into_a_deny(app, spy, fake_claude):
    settings.PERMISSION_TIMEOUT_SECS = 0.5
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    await wait_for_text(spy, LONG.strip(), timeout=4)
    assert fake_claude.decisions() == [{"behavior": "deny", "message": "User did not answer within 1 minutes."}]
    await wait_turn_finished(app)
    assert spy.calls("EditMessageText")[-1]["rich_message"]["markdown"].endswith("⌛ без ответа — отклонено")
    assert (await app.db.fetchrow("SELECT status FROM pending_prompts"))["status"] == "timeout"


async def test_second_press_on_an_answered_card_is_stale(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    mid = await card_message_id(app)
    await feed(app, callback_update("pa:1:1", message_id=mid))
    await wait_turn_finished(app)
    await run(app, callback_update("pd:1:1", message_id=mid))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Запрос уже неактуален"
    assert len(fake_claude.decisions()) == 1


async def test_cancel_while_a_card_waits_denies_and_marks_the_card(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    await feed(app, text_update("/cancel"))
    await wait_for_text(spy, "🛑 Прервано.")
    turn = await wait_turn_finished(app)
    assert turn["status"] == "cancelled"
    assert any(p["rich_message"]["markdown"].endswith("🛑 ход прерван") for p in spy.calls("EditMessageText"))
    assert (await app.db.fetchrow("SELECT status FROM pending_prompts"))["status"] == "cancelled"


async def test_waiting_state_is_shown_in_the_draft_and_the_card(app, spy, fake_claude):
    bash_turn(fake_claude)
    await feed(app, text_update("прогони тесты"))
    await wait_card(spy)
    for _ in range(50):
        if any("🔐 жду разрешения (Bash)" in p["rich_message"]["markdown"] for p in spy.calls("SendRichMessageDraft")):
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("waiting line never in a draft")
    await run(app, text_update("/status"))
    spy.assert_shown_text_contains("🔐 жду разрешения (Bash)")
    await feed(app, callback_update("pa:1:1", message_id=await card_message_id(app)))
    await wait_turn_finished(app)


async def test_write_card_shows_the_new_file_and_unknown_tool_is_masked(app, spy, fake_claude):
    fake_claude.enqueue(fc.prompt_tool("Write", {"file_path": "/work/new.py", "content": "print('hi')\n"}),
                        fc.prompt_tool("mcp__github__create_issue", {"title": "x", "api_token": "sk-verysecret"}, "toolu_2"),
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("создай"))
    card = await wait_card(spy)
    md = card["rich_message"]["markdown"]
    assert "`/work/new.py` (новый файл, 12 B)" in md and "```python\nprint('hi')\n```" in md
    await feed(app, callback_update("pa:1:1", message_id=await card_message_id(app)))
    card2 = await wait_card(spy, "mcp__github__create_issue")
    md2 = card2["rich_message"]["markdown"]
    assert "sk-verysecret" not in md2 and '"api_token": "•••"' in md2
    assert button_texts(card2)[2] == "Всегда: mcp__github__create_issue"
    await feed(app, callback_update("pd:1:2", message_id=await card_message_id(app)))
    await wait_turn_finished(app)
    assert [d["behavior"] for d in fake_claude.decisions()] == ["allow", "deny"]


async def test_dont_ask_mode_runs_without_the_prompt_tool(app, spy, fake_claude):
    await run(app, text_update("/perm dontAsk"))
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, LONG.strip())
    argv = fake_claude.argv_calls()[-1]
    assert "--permission-prompt-tool" not in argv and "--mcp-config" not in argv


async def test_perm_forget_removes_bot_rules_from_the_local_settings_file(app, spy, fake_claude):
    bash_turn(fake_claude, command="git status")
    await feed(app, text_update("что в гите?"))
    await wait_card(spy)
    await feed(app, callback_update("pw:1:1", message_id=await card_message_id(app)))
    await wait_turn_finished(app)
    settings_file = Path(settings.DEFAULT_CWD) / ".claude" / "settings.local.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(json.dumps({"permissions": {"allow": ["Bash(git status *)", "Read"]}}))
    await run(app, text_update("/perm forget"))
    assert spy.last_text() == "Забыла 1 правил. Снова буду спрашивать."
    assert json.loads(settings_file.read_text())["permissions"]["allow"] == ["Read"]
    assert await app.db.fetchval("SELECT count(*) FROM topic_rules") == 0
    await run(app, text_update("/perm forget"))
    assert spy.last_text() == "В этой теме я правил не добавляла."


async def test_daemon_restart_marks_pending_prompts_stale(app, spy, fake_claude, db):
    await run(app, text_update("/status"))
    await app.store.prompts.create(1, None, "permission", "Bash", "t", {"command": "ls"})
    from app.app import App
    other = App(app.bot, db)
    await other.outbox.stop(0)          # not started; keep it inert
    assert await other.store.prompts.mark_all_stale() == 1
    assert (await app.db.fetchrow("SELECT status FROM pending_prompts"))["status"] == "stale"
