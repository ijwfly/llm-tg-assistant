"""Outer middlewares on Update: access control (two locks) and update_id deduplication."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update

import settings
from app.store.repos import Store
from app.transport import texts

log = logging.getLogger(__name__)


def extract_actor(update: Update) -> tuple[int | None, int | None, str | None]:
    """(user_id, chat_id, chat_type) for the update kinds the bot handles."""
    msg = update.message or update.edited_message
    if msg is not None:
        return (msg.from_user.id if msg.from_user else None), msg.chat.id, msg.chat.type
    if update.callback_query is not None:
        cq = update.callback_query
        chat = cq.message.chat if cq.message is not None else None
        return cq.from_user.id, (chat.id if chat else None), (chat.type if chat else None)
    if update.stopped_message_generation is not None:
        chat = update.stopped_message_generation.chat
        user = chat.id if chat.type == "private" else None
        return user, chat.id, chat.type
    if update.my_chat_member is not None:
        m = update.my_chat_member
        return m.from_user.id, m.chat.id, m.chat.type
    return None, None, None


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
                       event: Update, data: dict[str, Any]) -> Any:
        user_id, chat_id, _ = extract_actor(event)
        if user_id not in settings.ALLOWED_USERS:
            log.info("ignored update %s from user %s in chat %s (not allowed)", event.update_id, user_id, chat_id)
            if event.callback_query is not None:
                await event.callback_query.answer(texts.NOT_AUTHORIZED)
            return None
        if settings.ALLOWED_CHATS and chat_id not in settings.ALLOWED_CHATS:
            log.info("ignored update %s in chat %s (chat not allowed)", event.update_id, chat_id)
            return None
        return await handler(event, data)


class DedupMiddleware(BaseMiddleware):
    """Marks the update processed *before* handling: a replayed update must never re-run a turn."""

    def __init__(self, store: Store):
        self.store = store

    async def __call__(self, handler, event: Update, data: dict[str, Any]) -> Any:
        if not await self.store.updates.mark_processed(event.update_id):
            log.info("duplicate update %s skipped", event.update_id)
            return None
        return await handler(event, data)
