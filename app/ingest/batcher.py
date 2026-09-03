"""Sliding-window batcher: everything a topic receives within BATCH_WINDOW_MS is one turn."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiogram.types import Message

import settings

log = logging.getLogger(__name__)


class Batcher:
    def __init__(self, flush: Callable[[dict, list[Message], list[str]], Awaitable[None]]):
        self._flush = flush
        self._buffers: dict[int, tuple[dict, list[Message], list[str]]] = {}
        self._timers: dict[int, asyncio.TimerHandle] = {}

    def add(self, topic: dict, message: Message, flag: str | None = None) -> None:
        """`flag` marks special items, e.g. "edited"."""
        key = topic["id"]
        if key not in self._buffers:
            self._buffers[key] = (topic, [], [])
        self._buffers[key][1].append(message)
        if flag:
            self._buffers[key][2].append(flag)
        timer = self._timers.pop(key, None)
        if timer:
            timer.cancel()
        loop = asyncio.get_running_loop()
        self._timers[key] = loop.call_later(settings.BATCH_WINDOW_MS / 1000, self._fire, key)

    def _fire(self, key: int) -> None:
        self._timers.pop(key, None)
        topic, messages, flags = self._buffers.pop(key)
        messages.sort(key=lambda m: m.message_id)
        asyncio.create_task(self._safe_flush(topic, messages, flags), name=f"batch-{key}")

    async def _safe_flush(self, topic: dict, messages: list[Message], flags: list[str]) -> None:
        try:
            await self._flush(topic, messages, flags)
        except Exception:
            log.exception("batch flush failed for topic %s", topic["id"])

    def pending(self, topic_id: int) -> int:
        buf = self._buffers.get(topic_id)
        return len(buf[1]) if buf else 0
