"""Outbox worker: at-least-once delivery, ordered per topic, parallel across topics."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiogram.methods
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import FSInputFile, Message

import settings
from app.render.markdown import PLAIN_LIMIT, split_text
from app.store.repos import OutboxRepo, OutboxRow, MessageLinksRepo

log = logging.getLogger(__name__)


class PermanentDeliveryError(Exception):
    """A Bad Request that will not succeed on retry."""


class OutboxWorker:
    def __init__(self, bot: Bot, repo: OutboxRepo, links: MessageLinksRepo):
        self.bot = bot
        self.repo = repo
        self.links = links
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._inflight: set[str] = set()
        self._stopping = False

    def wake(self) -> None:
        self._wake.set()

    @property
    def inflight(self) -> int:
        return len(self._inflight)

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="outbox-worker")

    async def stop(self, drain_secs: float | None = None) -> None:
        """Keep delivering for up to drain_secs, then stop the loop."""
        if self._task is None:
            return
        drain = settings.SHUTDOWN_DRAIN_SECS if drain_secs is None else drain_secs
        deadline = asyncio.get_running_loop().time() + drain
        while asyncio.get_running_loop().time() < deadline:
            if not self._inflight and not await self.repo.has_due_pending(set()):
                break
            await asyncio.sleep(0.05)
        self._stopping = True
        self.wake()
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                rows = await self.repo.next_batch(self._inflight)
            except Exception:
                log.exception("outbox: failed to fetch batch")
                rows = []
            for row in rows:
                self._inflight.add(row.topic_key)
                asyncio.create_task(self._deliver(row), name=f"outbox-{row.id}")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=settings.OUTBOX_POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _send(self, row: OutboxRow) -> int | None:
        method_cls = getattr(aiogram.methods, row.method)
        payload = dict(row.payload)
        for key in ("document", "photo", "voice", "audio", "video"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("file://"):
                payload[key] = FSInputFile(value[len("file://"):])
        method = method_cls.model_validate(payload)
        try:
            result = await self.bot(method)
        except TelegramBadRequest as e:
            if "not modified" in e.message:      # an edit to identical content: nothing to do
                return None
            if row.method == "SendRichMessage":
                log.warning("outbox %s: rich message rejected (%s), falling back to plain text", row.id, e.message)
                return await self._send_plain_fallback(row)
            raise PermanentDeliveryError(e)
        return result.message_id if isinstance(result, Message) else None

    async def _send_plain_fallback(self, row: OutboxRow) -> int | None:
        rich = row.payload.get("rich_message") or {}
        text = rich.get("markdown") or rich.get("html") or ""
        first_id = None
        reply = row.payload.get("reply_parameters")
        for chunk in split_text(text, PLAIN_LIMIT):
            msg = await self.bot(SendMessage(chat_id=row.payload["chat_id"], text=chunk,
                                             message_thread_id=row.payload.get("message_thread_id"),
                                             reply_parameters=reply))
            reply = None
            first_id = first_id or msg.message_id
        return first_id

    async def _deliver(self, row: OutboxRow) -> None:
        try:
            message_id = await self._send(row)
            await self.repo.mark_delivered(row.id, message_id)
            if message_id and row.topic_id:
                await self.links.link(row.payload["chat_id"], message_id, row.topic_id, row.role or "bot", row.turn_id)
        except TelegramRetryAfter as e:
            log.warning("outbox %s: rate limited for %ss (%s)", row.id, e.retry_after, row.topic_key)
            await self.repo.reschedule(row.id, e.retry_after, str(e), count_attempt=False)
        except (PermanentDeliveryError, TelegramForbiddenError) as e:
            # Telegram refused the payload for good (message gone, bot blocked): retrying would only
            # block the topic's queue behind this row.
            log.warning("outbox %s: permanent failure: %s", row.id, e)
            await self.repo.mark_failed(row.id, repr(e))
        except Exception as e:  # network errors, 5xx, bad payloads
            age = (datetime.now(timezone.utc) - row.created_at).total_seconds()
            if age > settings.OUTBOX_MAX_AGE_SECS:
                log.error("outbox %s: giving up after %.0fs: %s", row.id, age, e)
                await self.repo.mark_failed(row.id, repr(e))
            else:
                delay = min(settings.OUTBOX_RETRY_BASE_SECS * (2 ** row.attempts), settings.OUTBOX_RETRY_MAX_SECS)
                log.warning("outbox %s: %r, retry in %.2fs", row.id, e, delay)
                await self.repo.reschedule(row.id, delay, repr(e), count_attempt=True)
        finally:
            self._inflight.discard(row.topic_key)
            self.wake()
