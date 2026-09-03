import asyncio

import settings
from tests.support.helpers import run, feed
from tests.support.updates import callback_update, text_update


async def test_stranger_message_is_ignored_silently(app, spy):
    await feed(app, text_update("/help", user_id=999, chat_id=999))
    await asyncio.sleep(0.1)
    spy.assert_nothing_sent()
    assert await app.topics.list_all() == []


async def test_stranger_callback_gets_not_authorized_toast(app, spy):
    await feed(app, callback_update("perm:allow:1", user_id=999, chat_id=999))
    await asyncio.sleep(0.1)
    answers = spy.calls("AnswerCallbackQuery")
    assert len(answers) == 1 and answers[0]["text"] == "Not authorized"
    assert spy.sent_texts() == []


async def test_allowed_chats_blocks_other_chats(app, spy):
    settings.ALLOWED_CHATS = [42]
    await feed(app, text_update("/help", user_id=1, chat_id=1))
    await asyncio.sleep(0.1)
    spy.assert_nothing_sent()
    await run(app, text_update("/help", user_id=1, chat_id=42, chat_type="supergroup"))
    assert spy.sent_texts(chat_id=42)


async def test_allowed_user_gets_help(app, spy):
    await run(app, text_update("/help"))
    spy.assert_shown_text_contains("Тема = папка, в ней — текущая сессия")
