"""Dispatcher wiring: middlewares, routers, command menu, allowed updates."""
from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import BotCommand

from app.store.repos import Store
from app.transport.handlers import build_router
from app.transport.middleware import AccessMiddleware, DedupMiddleware

ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "stopped_message_generation", "my_chat_member"]

BOT_COMMANDS = [
    BotCommand(command="status", description="Карточка темы"),
    BotCommand(command="new", description="Новый контекст"),
    BotCommand(command="help", description="Справка"),
]


def build_dispatcher(app, store: Store) -> Dispatcher:
    dp = Dispatcher()
    dp["app"] = app
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(DedupMiddleware(store))
    dp.include_router(build_router())
    return dp
