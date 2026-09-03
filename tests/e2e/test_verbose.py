import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Посмотрел файл, вот выводы по нему, достаточно длинные, чтобы уйти в чат сразу одним сообщением целиком. " * 2


def rich(spy):
    return [p["rich_message"]["markdown"] for p in spy.calls("SendRichMessage")]


async def test_verbose_tools_shows_results_in_details(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("tgl:1:verbose_tools", message_id=500))
    assert (await app.topics.list_all())[0]["settings"]["verbose_tools"] is True
    fake_claude.enqueue(fc.tool_use("Read", {"file_path": "/work/proj/main.py"}), fc.tool_result("toolu_1", "print('hi')\n" * 3),
                        fc.tool_use("Bash", {"command": "pytest -q"}, "toolu_2"),
                        {"type": "user", "session_id": "{session_id}",
                         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_2",
                                                                  "content": [{"type": "text", "text": "x" * 4000}], "is_error": True}]}},
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("прочитай main.py"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    cards = [m for m in rich(spy) if m.startswith("<details>")]
    assert cards[0].startswith("<details><summary>Read /work/proj/main.py</summary>") and "print('hi')" in cards[0]
    assert cards[1].startswith("<details><summary>⚠️ Bash pytest -q</summary>") and "… (обрезано)" in cards[1]
    assert len(cards[1]) < 3800
    assert rich(spy).index(cards[1]) < rich(spy).index(next(m for m in rich(spy) if m.startswith("Посмотрел")))


async def test_verbose_off_is_silent_and_subagent_text_needs_the_flag(app, spy, fake_claude):
    fake_claude.enqueue(fc.tool_use("Read", {"file_path": "/w/a.py"}), fc.tool_result(),
                        {"type": "assistant", "session_id": "{session_id}", "parent_tool_use_id": "toolu_task",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "Я подагент, нашёл три бага"}]}},
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("проверь"))
    await wait_for_text(spy, LONG.strip())
    await wait_turn_finished(app)
    assert not any(m.startswith("<details>") for m in rich(spy))
    assert "--forward-subagent-text" not in fake_claude.argv_calls()[-1]
    settings.FORWARD_SUBAGENT_TEXT = True
    await run(app, callback_update("stop:1"))
    fake_claude.enqueue({"type": "assistant", "session_id": "{session_id}", "parent_tool_use_id": "toolu_task",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "Я подагент, нашёл три бага"}]}},
                        fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("ещё раз"))
    await wait_turn_finished(app, after=1)
    assert "--forward-subagent-text" in fake_claude.argv_calls()[-1]
    assert any(m == "<details><summary>Подагент</summary>\n\nЯ подагент, нашёл три бага\n\n</details>" for m in rich(spy))


async def test_failed_turn_gets_a_reaction_on_the_users_message(app, spy, fake_claude):
    fake_claude.enqueue(fc.assistant_text(LONG), fc.result(subtype="error_during_execution", is_error=True, text="boom"))
    await feed(app, text_update("сломайся", message_id=777))
    await wait_turn_finished(app)
    reaction = spy.calls("SetMessageReaction")[-1]
    assert reaction["message_id"] == 777 and reaction["reaction"][0]["emoji"] == "👾"
    fake_claude.text_turn(LONG)
    await feed(app, text_update("нормально", message_id=778))
    await wait_turn_finished(app, after=1)
    assert len(spy.calls("SetMessageReaction")) == 1


async def test_crash_and_disabled_reactions(app, spy, fake_claude):
    await app.store.users.upsert(1, "Test User", "tester")
    await app.store.users.update_settings(1, reactions=False)
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    await feed(app, text_update("упади", message_id=779))
    await wait_for_text(spy, "💥")
    await wait_turn_finished(app)
    assert spy.calls("SetMessageReaction") == []
    await app.store.users.update_settings(1, reactions=True)
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    await feed(app, text_update("упади снова", message_id=780))
    await wait_turn_finished(app, after=1)
    assert spy.calls("SetMessageReaction")[-1]["message_id"] == 780
