import asyncio

from app.transport.bot import BOT_COMMANDS
from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_for_text, wait_outbox_idle, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Достаточно длинный ответ, чтобы он ушёл в чат сразу, а не ждал следующего сегмента текста. " * 2


def card_buttons(payload):
    return [b["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def test_status_sends_a_card_with_buttons(app, spy):
    await run(app, text_update("/status"))
    card = spy.calls("SendMessage")[-1]
    assert card["text"].startswith("Тема")
    assert card_buttons(card) == ["new:1", "stop:1", "cyc:1:perm", "cyc:1:model", "cyc:1:effort", "sessions:1", "branch:1",
                                  "page:1:more", "refresh:1", "hide:1", "del:1"]


async def test_card_shows_cancel_while_a_turn_runs(app, spy, fake_claude):
    fake_claude.enqueue({"delay": 1}, fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("работай"))
    await asyncio.sleep(0.1)
    await run(app, text_update("/status"))
    card = next(p for p in spy.calls("SendMessage") if p["text"].startswith("Тема"))
    assert card_buttons(card)[0] == "cancel:1"
    await wait_turn_finished(app)


async def test_new_button_starts_a_new_context_and_redraws_the_card(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_turn_finished(app)
    before = (await app.topics.list_all())[0]["session_id"]
    await run(app, callback_update("new:1", message_id=500))
    after = (await app.topics.list_all())[0]["session_id"]
    assert before != after
    spy.assert_shown_text_contains("🆕 Новый контекст")
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == 500 and str(after) in edit["text"]
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Новый контекст"


async def test_stop_and_refresh_buttons(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет"))
    await wait_turn_finished(app)
    assert app.runtimes.peek(1).proc is not None
    await run(app, callback_update("stop:1", message_id=500))
    assert app.runtimes.peek(1).proc is None
    assert "⏸ Процесс остановлен, контекст сохранён." in spy.sent_texts()
    await run(app, callback_update("refresh:1", message_id=500))
    assert spy.calls("EditMessageText")[-1]["text"].count("Процесс      спит") == 1
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Обновлено"


async def test_hide_button_deletes_the_card(app, spy):
    await run(app, text_update("/status"))
    await run(app, callback_update("hide:1", message_id=500))
    assert spy.calls("DeleteMessage")[-1]["message_id"] == 500


async def test_stale_button_answers_with_a_toast(app, spy):
    await run(app, callback_update("retry:999"))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Уже неактуально"
    await run(app, callback_update("garbage"))
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Уже неактуально"
    assert spy.sent_texts() == []


async def test_retry_button_on_a_verdict_reruns_the_turn(app, spy, fake_claude):
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.enqueue({"exit": 2, "stderr": "boom"})
    fake_claude.text_turn(LONG)
    await feed(app, text_update("сделай"))
    await wait_for_text(spy, "💥")
    verdict = spy.calls("SendMessage")[-1]
    assert card_buttons(verdict) == ["retry:1"]
    await feed(app, callback_update("retry:1"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts()[-1] == "сделай"


async def test_denied_verdict_offers_accept_edits(app, spy, fake_claude):
    fake_claude.enqueue(fc.permission_denied("Write"), fc.assistant_text(LONG), fc.result())
    await feed(app, text_update("создай файл"))
    await wait_for_text(spy, "🔒 Отклонено без спроса: Write")
    verdict = next(p for p in spy.calls("SendMessage") if p["text"].startswith("🔒"))
    assert card_buttons(verdict) == ["perm:1:acceptEdits", "retry:1"]
    await run(app, callback_update("perm:1:acceptEdits"))
    assert (await app.topics.list_all())[0]["permission_mode"] == "acceptEdits"
    assert any(t.startswith("🔐 Права: acceptEdits") for t in spy.sent_texts())
    fake_claude.text_turn("Теперь правки проходят. " + LONG)
    await feed(app, text_update("ещё раз"))
    await wait_for_text(spy, "Теперь правки проходят.")
    argv = fake_claude.argv_calls()[-1]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"


async def test_continue_button_after_a_limit(app, spy, fake_claude):
    fake_claude.enqueue(fc.result(subtype="error_max_turns", is_error=True))
    fake_claude.text_turn(LONG)
    await feed(app, text_update("много работы"))
    await wait_for_text(spy, "⏹ Достигнут лимит ходов")
    await feed(app, callback_update("continue:1"))
    await wait_for_text(spy, LONG.strip())
    assert fake_claude.stdin_texts()[-1] == "продолжай"


async def test_perm_command_shows_and_sets_mode(app, spy):
    await run(app, text_update("/perm"))
    assert "← prompt" in spy.last_text()
    await run(app, text_update("/perm plan"))
    assert (await app.topics.list_all())[0]["permission_mode"] == "plan"
    await run(app, text_update("/perm bypass"))
    assert "Не знаю режим bypass" in spy.last_text()


def test_command_menu_lists_every_bridge_command():
    from app.transport.handlers import build_router
    registered = set()
    for handler in build_router().message.handlers:
        for f in handler.filters or []:
            registered |= {c if isinstance(c, str) else c.pattern for c in getattr(f.callback, "commands", ())}
    menu = [c.command for c in BOT_COMMANDS]
    assert len(menu) == len(set(menu))
    assert set(menu) == registered - {"start", "clear"}     # aliases stay out of the menu
    assert all(len(c.description) <= 256 for c in BOT_COMMANDS)
