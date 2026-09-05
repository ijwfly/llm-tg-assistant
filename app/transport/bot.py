"""Dispatcher wiring: middlewares, routers, command menu, allowed updates."""
from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import BotCommand

from app.store.repos import Store
from app.transport.handlers import build_router
from app.transport.middleware import AccessMiddleware, DedupMiddleware

ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "stopped_message_generation", "my_chat_member"]

# Every bridge command (PROJECT_SPEC 4.3.0): only what needs an argument or has no button; the rest are buttons
BOT_COMMANDS = [
    BotCommand(command="status", description="Карточка темы: состояние, настройки, все кнопки"),
    BotCommand(command="new", description="Новый контекст в этой теме"),
    BotCommand(command="project", description="Тема под папку: /project <алиас|путь> или new <имя>"),
    BotCommand(command="rename", description="Переименовать тему и сессию: /rename <имя>"),
    BotCommand(command="plan", description="Режим плана: только чтение, план приходит карточкой"),
    BotCommand(command="auto", description="Режим auto: Claude Code решает сам, спорное — карточкой"),
    BotCommand(command="files", description="Последние файлы темы"),
    BotCommand(command="usage", description="Расход за месяц"),
    BotCommand(command="help", description="Справка"),
]


def build_dispatcher(app, store: Store) -> Dispatcher:
    dp = Dispatcher()
    dp["app"] = app
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(DedupMiddleware(store))
    dp.include_router(build_router())
    return dp
