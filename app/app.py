"""Application object: wires store, sender, outbox worker, topics, runtimes and the dispatcher."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.methods import SetMyCommands

import settings
from app.core.runtime import RuntimeRegistry
from app.core.topics import TopicService
from app.store.db import Database
from app.store.repos import Store
from app.transport import texts
from app.transport.bot import BOT_COMMANDS, build_dispatcher
from app.transport.outbox import OutboxWorker
from app.transport.sender import TelegramSender

VERSION = "0.2.0-phase2"
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
        self.outbox = OutboxWorker(bot, self.store.outbox, self.store.links)
        self.sender = TelegramSender(self.store, self.outbox.wake)
        self.topics = TopicService(self.store)
        self.runtimes = RuntimeRegistry(self)
        self.dp = build_dispatcher(self, self.store)
        self._stopped = False

    async def start(self) -> None:
        self._stopped = False
        await self.outbox.start()
        notify = parse_notify_chat(settings.NOTIFY_CHAT)
        if notify:
            me = await self.bot.me()
            topics = len(await self.topics.list_all())
            await self.sender.send_text(notify[0], notify[1], texts.STARTUP.format(
                username=me.username, mode=settings.DEFAULT_PERMISSION_MODE, topics=topics, version=VERSION))
        log.info("app started")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        await self.runtimes.shutdown_all()
        notify = parse_notify_chat(settings.NOTIFY_CHAT)
        if notify:
            await self.sender.send_text(notify[0], notify[1], texts.SHUTDOWN)
        await self.outbox.stop()
        log.info("app stopped")

    async def register_commands(self) -> None:
        await self.bot(SetMyCommands(commands=BOT_COMMANDS))
