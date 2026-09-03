"""Dispatcher wiring: middlewares, routers, command menu, allowed updates."""
from __future__ import annotations

from aiogram import Dispatcher
from aiogram.types import BotCommand

from app.store.repos import Store
from app.transport.handlers import build_router
from app.transport.middleware import AccessMiddleware, DedupMiddleware

ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "stopped_message_generation", "my_chat_member"]

# Every bridge command, registered in the Telegram «/» menu (the user's call: all of them visible)
BOT_COMMANDS = [
    BotCommand(command="status", description="Карточка темы: состояние, настройки, кнопки"),
    BotCommand(command="new", description="Новый контекст в этой теме"),
    BotCommand(command="cancel", description="Прервать текущий ход"),
    BotCommand(command="retry", description="Повторить последний ход"),
    BotCommand(command="stop", description="Погасить процесс, контекст сохранить"),
    BotCommand(command="sessions", description="Сессии Claude Code на машине"),
    BotCommand(command="resume", description="Подключить сессию: /resume <id|имя>"),
    BotCommand(command="branch", description="Новая тема с копией контекста: /branch [имя]"),
    BotCommand(command="project", description="Тема под папку: /project <алиас|путь> или new <имя>"),
    BotCommand(command="rename", description="Переименовать тему и сессию: /rename <имя>"),
    BotCommand(command="delete", description="Удалить эту тему"),
    BotCommand(command="cd", description="Сменить папку темы: /cd <путь>"),
    BotCommand(command="go", description="Сменить папку по алиасу: /go [алиас]"),
    BotCommand(command="perm", description="Права темы: /perm [режим|forget]"),
    BotCommand(command="model", description="Модель темы: /model [имя|default]"),
    BotCommand(command="effort", description="Усилие темы: /effort [low…max|default]"),
    BotCommand(command="soul", description="Персона: /soul [путь|off|default]"),
    BotCommand(command="voice", description="Голосовые ответы: /voice on|off"),
    BotCommand(command="files", description="Последние файлы темы"),
    BotCommand(command="usage", description="Расход за месяц"),
    BotCommand(command="topics", description="Темы бота"),
    BotCommand(command="whoami", description="Твой id, чат и тема"),
    BotCommand(command="help", description="Справка"),
]


def build_dispatcher(app, store: Store) -> Dispatcher:
    dp = Dispatcher()
    dp["app"] = app
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(DedupMiddleware(store))
    dp.include_router(build_router())
    return dp
