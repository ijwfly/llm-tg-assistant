"""Outbox worker: at-least-once delivery, ordered per topic, parallel across topics."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiogram.methods
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message

import settings
from app.store.repos import OutboxRepo, OutboxRow

log = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(self, bot: Bot, repo: OutboxRepo):
        self.bot = bot
        self.repo = repo
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
        drain = settings.SHUTDOWN_DRAIN_SECS if drain_secs is None else drain_secs
        deadline = asyncio.get_running_loop().time() + drain
        while asyncio.get_running_loop().time() < deadline:
            if not self._inflight and not await self.repo.has_due_pending(set()):
                break
            await asyncio.sleep(0.05)
        self._stopping = True
        self.wake()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()

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

    async def _deliver(self, row: OutboxRow) -> None:
        try:
            method_cls = getattr(aiogram.methods, row.method)
            method = method_cls.model_validate(row.payload)
            result = await self.bot(method)
            message_id = result.message_id if isinstance(result, Message) else None
            await self.repo.mark_delivered(row.id, message_id)
        except TelegramRetryAfter as e:
            log.warning("outbox %s: rate limited for %ss (%s)", row.id, e.retry_after, row.topic_key)
            await self.repo.reschedule(row.id, e.retry_after, str(e), count_attempt=False)
        except Exception as e:  # network errors, API errors, bad payloads
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
