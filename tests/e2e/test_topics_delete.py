from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteForumTopic

from tests.support import fake_claude as fc
from tests.support.helpers import feed, run, wait_turn_finished
from tests.support.updates import callback_update, text_update

LONG = "Ответ в теме, которую потом удалим, достаточно длинный, чтобы уйти сразу одним сообщением в чат. " * 2


def button_texts(payload):
    return [b["text"] for row in payload["reply_markup"]["inline_keyboard"] for b in row]


async def test_delete_button_asks_then_deletes_the_topic_and_forgets_it(app, spy, fake_claude):
    fake_claude.text_turn(LONG)
    await feed(app, text_update("привет", thread_id=5, topic_name="Проект"))
    await wait_turn_finished(app)
    assert app.runtimes.peek(1).proc is not None
    await run(app, text_update("/status", thread_id=5, topic_name="Проект"))
    assert "Удалить тему" in button_texts(spy.calls("SendMessage")[-1])
    await run(app, callback_update("del:1", message_id=500))
    edit = spy.calls("EditMessageText")[-1]
    assert edit["message_id"] == 500 and edit["text"].startswith("Удалить тему «Проект» вместе с сообщениями?")
    assert button_texts(edit) == ["Да, удалить тему", "Отмена"]
    assert spy.calls("DeleteForumTopic") == []
    await run(app, callback_update("delc:1", message_id=500))
    assert spy.calls("DeleteForumTopic")[-1] == {"chat_id": 1, "message_thread_id": 5}
    assert spy.calls("AnswerCallbackQuery")[-1]["text"] == "Тема удалена"
    assert await app.topics.list_all() == []
    assert await app.db.fetchval("SELECT count(*) FROM turns") == 0
    assert app.runtimes.peek(1) is None


async def test_cancel_redraws_the_card(app, spy, fake_claude):
    await run(app, text_update("/status", thread_id=5, topic_name="Проект"))
    await run(app, callback_update("del:1", message_id=500))
    await run(app, callback_update("refresh:1", message_id=500))
    edit = spy.calls("EditMessageText")[-1]
    assert edit["text"].startswith("Тема") and "Удалить тему" in button_texts(edit)
    assert len(await app.topics.list_all()) == 1


async def test_delete_refused_by_telegram_keeps_the_topic(app, spy, fake_claude):
    await run(app, text_update("/status", thread_id=5, topic_name="Проект"))
    app.bot.session.fail_next("DeleteForumTopic", TelegramBadRequest(
        method=DeleteForumTopic(chat_id=1, message_thread_id=5), message="Bad Request: not enough rights"))
    await run(app, callback_update("delc:1", message_id=500))
    assert spy.last_text() == "⚠️ Не могу удалить тему: Bad Request: not enough rights"
    assert len(await app.topics.list_all()) == 1


async def test_delete_in_the_chat_itself_is_refused(app, spy, fake_claude):
    await run(app, text_update("/status"))
    await run(app, callback_update("del:1", message_id=500))
    assert spy.last_text() == "Это не тема, а сам чат — удалять нечего."
    assert spy.calls("DeleteForumTopic") == [] and len(await app.topics.list_all()) == 1
