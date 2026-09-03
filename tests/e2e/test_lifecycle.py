from aiogram import Bot

import settings
from app.app import App
from tests.support.helpers import wait_outbox_idle
from tests.support.spy import TelegramSpy


async def test_notify_chat_gets_startup_and_shutdown_messages(db, session):
    settings.NOTIFY_CHAT = "777:5"
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, session=session)
    application = App(bot, db)
    spy = TelegramSpy(session)
    try:
        await application.start()
        await wait_outbox_idle(application)
        assert spy.sent_texts(chat_id=777)[0].startswith("🌅 Я на месте. Бот @testbot, режим prompt, тем: 0")
        assert spy.calls("SendMessage")[0]["message_thread_id"] == 5
    finally:
        await application.stop()
        await bot.session.close()
    assert spy.sent_texts(chat_id=777)[-1] == "⏹ Останавливаюсь."
