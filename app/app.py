"""Application object: wires store, sender, outbox worker, topics, runtimes and the dispatcher."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.methods import SetMyCommands

import settings
from app.bridge.socket_server import BridgeSocket
from app.core.prompts import PromptService
from app.core.runtime import RuntimeRegistry
from app.core.topics import TopicService
from app.ingest.batcher import Batcher
from app.ingest.files import InboxService
from app.ingest.pipeline import Ingest
from app.store.db import Database
from app.store.repos import Store
from app.transport import texts
from app.transport.bot import BOT_COMMANDS, build_dispatcher
from app.transport.outbox import OutboxWorker
from app.transport.sender import TelegramSender

VERSION = "0.5.0-phase5"
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
        self.prompts = PromptService(self)
        self.bridge_socket = BridgeSocket(self)
        self.runtimes = RuntimeRegistry(self)
        self.inbox = InboxService(self)
        self.ingest = Ingest(self)
        self.batcher = Batcher(self.ingest.process_batch)
        self.dp = build_dispatcher(self, self.store)
        self._stopped = False
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._stopped = False
        await self.outbox.start()
        stale = await self.store.prompts.mark_all_stale()   # cards from before the restart cannot be answered
        if stale:
            log.info("marked %s pending prompts stale", stale)
        await self.bridge_socket.start()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="inbox-cleanup")
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
        await self.bridge_socket.stop()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        notify = parse_notify_chat(settings.NOTIFY_CHAT)
        if notify:
            await self.sender.send_text(notify[0], notify[1], texts.SHUTDOWN)
        await self.outbox.stop()
        log.info("app stopped")

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await self.inbox.cleanup()
            except Exception:
                log.exception("inbox cleanup failed")
            await asyncio.sleep(6 * 3600)

    async def register_commands(self) -> None:
        await self.bot(SetMyCommands(commands=BOT_COMMANDS))
