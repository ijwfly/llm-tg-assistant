"""Live indicator of a running turn: a rich draft (private chats) or an editable progress message."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputRichMessage

import settings
from app.render.keyboards import cancel_kb

log = logging.getLogger(__name__)


class LiveView:
    """One per turn. `render_draft()` / `render_message()` are supplied by the runtime and read the
    turn state; `touch()` asks for a refresh through a trailing-edge gate."""

    def __init__(self, app, *, chat_id: int, thread_id: int | None, topic_id: int, turn_id: int,
                 private: bool, render_draft: Callable[[], str], render_message: Callable[[], str]):
        self.app = app
        self.chat_id, self.thread_id, self.topic_id, self.turn_id = chat_id, thread_id, topic_id, turn_id
        self.mode = "draft" if (private and settings.USE_DRAFTS) else "message"
        self.render_draft = render_draft
        self.render_message = render_message
        self.message_id: int | None = None
        self.last_sent: str | None = None
        self._next_allowed = 0.0
        self._pending: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._delay: asyncio.Task | None = None
        self._finished = False
        self._started = time.monotonic()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self.mode == "message":
            self._delay = asyncio.create_task(self._show_after_delay())
        else:
            self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def _show_after_delay(self) -> None:
        await asyncio.sleep(settings.PROGRESS_DELAY)
        self.touch()

    async def _keepalive_loop(self) -> None:
        while not self._finished:
            await asyncio.sleep(settings.DRAFT_KEEPALIVE)
            if self.last_sent is not None:
                self.touch(force=True)

    def touch(self, force: bool = False) -> None:
        if self._finished:
            return
        if force:
            self.last_sent = None
        if self._pending is None or self._pending.done():
            self._pending = asyncio.create_task(self._flush_when_allowed())

    async def finish(self) -> None:
        """Stop updating. The progress message is deleted through the outbox so it disappears
        after the final answer; a draft vanishes on its own once a real message is sent."""
        self._finished = True
        for t in (self._pending, self._keepalive, self._delay):
            if t:
                t.cancel()
        if self.mode == "message" and self.message_id is not None:
            await self.app.sender.delete(self.chat_id, self.thread_id, self.message_id, topic_id=self.topic_id)
            self.message_id = None

    # ---------------------------------------------------------------- gate

    async def _flush_when_allowed(self) -> None:
        wait = self._next_allowed - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        if self._finished:
            return
        interval = settings.DRAFT_MIN_INTERVAL if self.mode == "draft" else settings.EDIT_MIN_INTERVAL
        self._next_allowed = time.monotonic() + interval
        try:
            await self._send_latest()
        except TelegramRetryAfter as e:
            log.warning("live view rate limited for %ss", e.retry_after)
            self._next_allowed = time.monotonic() + e.retry_after
            self.last_sent = None
        except Exception as e:  # cosmetic path: never break the turn
            log.debug("live view update failed: %r", e)

    async def _send_latest(self) -> None:
        if self.mode == "draft":
            content = self.render_draft()
            if content == self.last_sent:
                return
            try:
                await self.app.bot.send_rich_message_draft(
                    chat_id=self.chat_id, draft_id=self.turn_id, message_thread_id=self.thread_id,
                    rich_message=InputRichMessage(markdown=content), can_stop=True)
                self.last_sent = content
                return
            except TelegramBadRequest as e:
                log.warning("draft rejected (%s); switching to progress message", e.message)
                self.mode = "message"
                if self._keepalive:
                    self._keepalive.cancel()
                self.last_sent = None
        text = self.render_message()
        if text == self.last_sent:
            return
        kb = cancel_kb(self.topic_id)
        if self.message_id is None:
            msg = await self.app.bot.send_message(self.chat_id, text, message_thread_id=self.thread_id, reply_markup=kb)
            self.message_id = msg.message_id
        else:
            try:
                await self.app.bot.edit_message_text(text, chat_id=self.chat_id, message_id=self.message_id, reply_markup=kb)
            except TelegramBadRequest as e:
                if "not modified" in e.message:
                    pass
                else:  # message gone: recreate on the next update
                    log.info("progress message lost (%s)", e.message)
                    self.message_id = None
                    self.last_sent = None
                    return
        self.last_sent = text
