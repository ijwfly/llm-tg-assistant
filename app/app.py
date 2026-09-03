"""Application object: wires store, sender, outbox worker, topics and the dispatcher."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.methods import SetMyCommands

import settings
from app.core.topics import TopicService
from app.store.db import Database
from app.store.repos import Store
from app.transport import texts
from app.transport.bot import BOT_COMMANDS, build_dispatcher
from app.transport.outbox import OutboxWorker
from app.transport.sender import TelegramSender

VERSION = "0.1.0-phase1"
log = logging.getLogger(__name__)


def parse_notify_chat(value: str | None) -> tuple[int, int | None] | None:
    if not value:
        return None
    chat, _, thread = value.partition(":")
    return int(chat), (int(thread) if thread else None)


class App:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.store = Store(db)
        self.outbox = OutboxWorker(bot, self.store.outbox)
        self.sender = TelegramSender(self.store, self.outbox.wake)
        self.topics = TopicService(self.store)
        self.dp = build_dispatcher(self, self.store)

    async def start(self) -> None:
        await self.outbox.start()
        notify = parse_notify_chat(settings.NOTIFY_CHAT)
        if notify:
            me = await self.bot.me()
            topics = len(await self.topics.list_all())
            await self.sender.send_text(notify[0], notify[1], texts.STARTUP.format(
                username=me.username, mode=settings.DEFAULT_PERMISSION_MODE, topics=topics, version=VERSION))
        log.info("app started")

    async def stop(self) -> None:
        notify = parse_notify_chat(settings.NOTIFY_CHAT)
        if notify:
            await self.sender.send_text(notify[0], notify[1], texts.SHUTDOWN)
        await self.outbox.stop()
        log.info("app stopped")

    async def register_commands(self) -> None:
        await self.bot(SetMyCommands(commands=BOT_COMMANDS))
