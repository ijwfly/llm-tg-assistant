"""Dispatcher wiring: middlewares, routers, command menu, allowed updates."""
from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import BotCommand

from app.store.repos import Store
from app.transport.handlers import build_router
from app.transport.middleware import AccessMiddleware, DedupMiddleware

ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "stopped_message_generation", "my_chat_member"]

BOT_COMMANDS = [
    BotCommand(command="new", description="Новый контекст"),
    BotCommand(command="status", description="Состояние темы"),
    BotCommand(command="cancel", description="Прервать текущий ход"),
    BotCommand(command="retry", description="Повторить последний ход"),
    BotCommand(command="go", description="Сменить проект по алиасу"),
    BotCommand(command="cd", description="Сменить директорию"),
    BotCommand(command="compact", description="Сжать контекст (Claude Code)"),
    BotCommand(command="stop", description="Погасить процесс, контекст сохранить"),
    BotCommand(command="topics", description="Список тем"),
    BotCommand(command="whoami", description="Мой id, чат и тема"),
    BotCommand(command="help", description="Справка"),
]


def build_dispatcher(app, store: Store) -> Dispatcher:
    dp = Dispatcher()
    dp["app"] = app
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(DedupMiddleware(store))
    dp.include_router(build_router())
    return dp
