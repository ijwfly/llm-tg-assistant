"""Entry point: python -m app.main"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

import settings
from app.app import App
from app.store.db import Database
from app.transport.bot import ALLOWED_UPDATES

log = logging.getLogger("app.main")


def validate_settings() -> None:
    problems = []
    if not settings.TELEGRAM_BOT_TOKEN:
        problems.append("TELEGRAM_BOT_TOKEN is empty")
    if not settings.ALLOWED_USERS:
        problems.append("ALLOWED_USERS is empty (nobody could control the bot)")
    if settings.DEFAULT_PERMISSION_MODE == "bypass" and not settings.ALLOW_BYPASS:
        problems.append("DEFAULT_PERMISSION_MODE=bypass requires ALLOW_BYPASS=True")
    if problems:
        raise SystemExit("settings: " + "; ".join(problems))


async def run() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    validate_settings()
    db = await Database.connect(settings.DATABASE_URL)
    await db.migrate()
    bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    app = App(bot, db)
    try:
        await app.register_commands()
        await app.start()
        await app.dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await app.stop()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
