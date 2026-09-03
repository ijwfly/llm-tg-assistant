import json
from datetime import datetime, timezone

from aiogram.types import Message, Update, User

from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import chat, message, text_update, user


async def test_text_message_becomes_a_turn_and_the_answer_is_delivered(app, spy, fake_claude):
    fake_claude.text_turn("**Привет** из Claude", cost=0.05, num_turns=3)
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "**Привет** из Claude")
    rich = spy.calls("SendRichMessage")[-1]
    assert rich["rich_message"]["markdown"] == "**Привет** из Claude"
    turn = await wait_turn_finished(app)
    assert turn["status"] == "done" and turn["cost_usd"] == 0.05 and turn["num_turns"] == 3
    topic = (await app.topics.list_all())[0]
    assert topic["session_id"] is not None and topic["session_resumable"] is True
    argv = fake_claude.argv_calls()[0]
    assert argv[:3] == ["-p", "--verbose", "--input-format"]
    assert "--session-id" in argv and str(topic["session_id"]) in argv
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert fake_claude.stdin_texts() == ["привет"]
    link = await app.store.links.get(1, rich_message_id(spy))
    assert link and link["role"] == "assistant" and link["turn_id"] == turn["id"]


def rich_message_id(spy) -> int:
    # the recording session hands out ids from 1000 in call order; find the rich call's position
    for i, (name, _) in enumerate(spy.session.calls):
        if name == "SendRichMessage":
            return 1000 + sum(1 for n, _ in spy.session.calls[:i] if n in ("SendMessage", "SendRichMessage"))
    raise AssertionError("no rich message")


async def test_second_turn_reuses_the_running_process(app, spy, fake_claude):
    fake_claude.text_turn("раз")
    fake_claude.text_turn("два")
    await feed(app, text_update("первый"))
    await wait_for_text(spy, "раз")
    await wait_turn_finished(app)
    await feed(app, text_update("второй"))
    await wait_for_text(spy, "два")
    assert len(fake_claude.argv_calls()) == 1
    assert fake_claude.stdin_texts() == ["первый", "второй"]


async def test_turn_without_text_reports_done(app, spy, fake_claude):
    fake_claude.enqueue(fc.result())
    await feed(app, text_update("сделай тихо"))
    await wait_for_text(spy, "✔️ Готово")


async def test_compact_reports_compacted_context(app, spy, fake_claude):
    fake_claude.enqueue(fc.compact_boundary(1842), fc.result())
    await feed(app, text_update("/compact"))
    await wait_for_text(spy, "🧹 Контекст сжат: было 1842")
    assert fake_claude.stdin_texts() == ["/compact"]


async def test_error_result_is_reported(app, spy, fake_claude):
    fake_claude.enqueue(fc.result(subtype="error_during_execution", is_error=True, text="API key invalid"))
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "⚠️ Ход завершился с ошибкой: API key invalid")
    turn = await wait_turn_finished(app)
    assert turn["status"] == "error"


async def test_max_turns_limit_is_reported(app, spy, fake_claude):
    fake_claude.enqueue(fc.result(subtype="error_max_turns", is_error=True))
    await feed(app, text_update("привет"))
    await wait_for_text(spy, "⏹ Достигнут лимит ходов")


async def test_denied_tools_are_listed_at_the_end(app, spy, fake_claude):
    fake_claude.enqueue(fc.permission_denied("Edit"), fc.permission_denied("Bash"), fc.permission_denied("Edit"),
                        fc.assistant_text("не смог"), fc.result())
    await feed(app, text_update("поправь файл"))
    await wait_for_text(spy, "🔒 Отклонено без спроса: Edit, Bash")
    texts = spy.sent_texts()
    assert texts.index("не смог") < next(i for i, t in enumerate(texts) if t.startswith("🔒"))


async def test_reply_to_bot_message_is_quoted_in_the_prompt(app, spy, fake_claude):
    fake_claude.text_turn("ок")
    bot_msg = Message(message_id=77, date=datetime.now(timezone.utc), chat=chat(1),
                      from_user=User(id=app.bot.id, is_bot=True, first_name="bot"), text="Вот мой длинный ответ")
    await feed(app, Update(update_id=9001, message=message("уточни второй пункт", reply_to=bot_msg)))
    await wait_for_text(spy, "ок")
    assert fake_claude.stdin_texts() == ["[в ответ на твой ответ: «Вот мой длинный ответ»]\n\nуточни второй пункт"]


async def test_reply_to_other_message_is_quoted_as_message(app, spy, fake_claude):
    fake_claude.text_turn("ок")
    other = message("чужой текст", user_id=5)
    await feed(app, Update(update_id=9002, message=message("что это?", reply_to=other)))
    await wait_for_text(spy, "ок")
    assert fake_claude.stdin_texts()[0].startswith("[в ответ на сообщение: «чужой текст»]")


async def test_unknown_slash_command_goes_to_claude(app, spy, fake_claude):
    fake_claude.text_turn("Total cost: $0.42")
    await feed(app, text_update("/cost"))
    await wait_for_text(spy, "Total cost")
    assert fake_claude.stdin_texts() == ["/cost"]


async def test_clear_starts_a_new_context(app, spy, fake_claude):
    fake_claude.text_turn("a")
    fake_claude.text_turn("b")
    await feed(app, text_update("один"))
    await wait_for_text(spy, "a")
    await wait_turn_finished(app)
    first = (await app.topics.list_all())[0]["session_id"]
    await feed(app, text_update("/clear"))
    await wait_for_text(spy, "🆕 Новый контекст")
    await feed(app, text_update("два"))
    await wait_for_text(spy, "b")
    second = (await app.topics.list_all())[0]["session_id"]
    assert first != second
    argvs = fake_claude.argv_calls()
    assert len(argvs) == 2 and argvs[1][argvs[1].index("--session-id") + 1] == str(second)


async def test_turn_stats_caption_when_enabled(app, spy, fake_claude, monkeypatch):
    import settings
    settings.SHOW_TURN_STATS = True
    fake_claude.text_turn("готово", cost=0.08, num_turns=3, duration_ms=72000)
    await feed(app, text_update("сделай"))
    await wait_for_text(spy, "_1 м 12 с · $0.08 · 3 шагов_")
