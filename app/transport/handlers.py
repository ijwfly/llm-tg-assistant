"""Command and message handlers. `app` is injected from dispatcher workflow data.

Only commands that need an argument or have no button live here (PROJECT_SPEC 4.3.0): everything
else is a button on the topic card or on the message it belongs to (see callbacks.py)."""
from __future__ import annotations

import os
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, MessageGenerationStopped

import settings
from app.core import actions
from app.core.topics import TopicRef
from app.transport import texts
from app.transport.callbacks import on_callback

CONTENT_FILTER = F.text | F.caption | F.photo | F.document | F.voice | F.audio | F.video_note | F.video


def topic_ref(message: Message) -> TopicRef:
    thread = message.message_thread_id if message.is_topic_message else None
    return TopicRef(message.chat.id, thread)


def topic_title(message: Message) -> str | None:
    if message.chat.type == "private" and not message.is_topic_message:
        return None
    if message.is_topic_message and message.reply_to_message and message.reply_to_message.forum_topic_created:
        return message.reply_to_message.forum_topic_created.name
    return message.chat.title


def _implicit_title(message: Message) -> bool:
    created = message.reply_to_message.forum_topic_created if message.is_topic_message and message.reply_to_message else None
    return bool(created and created.is_name_implicit)


async def _remember_user(app, message: Message) -> None:
    u = message.from_user
    if u is not None:
        await app.store.users.upsert(u.id, u.full_name, u.username)


async def _topic(app, message: Message) -> dict:
    await _remember_user(app, message)
    topic = await app.topics.get_or_create(topic_ref(message), topic_title(message))
    if _implicit_title(message) and "title_implicit" not in (topic.get("settings") or {}):
        topic = await app.store.topics.update_settings(topic["id"], title_implicit=True)   # False after /rename
        topic = await actions.name_implicit_topic(app, topic)                              # named after its folder
    return topic


def resolve_cwd(raw: str) -> tuple[str | None, str | None]:
    """(path, error_text). The path must exist and live inside WORK_ROOT."""
    path = Path(os.path.expanduser(raw.strip())).resolve()
    root = Path(settings.WORK_ROOT).resolve()
    if not path.is_dir():
        return None, texts.CD_NO_DIR.format(path=path)
    if path != root and root not in path.parents:
        return None, texts.CD_OUTSIDE.format(path=path, root=root)
    return str(path), None


# ------------------------------------------------------------------ commands

async def cmd_help(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id,
                               texts.help(message.from_user.id if message.from_user else 0, ref.chat_id, ref.thread_id))


async def cmd_status(message: Message, app) -> None:
    await actions.show_card(app, await _topic(app, message), user_id=message.from_user.id if message.from_user else None)


async def cmd_new(message: Message, app) -> None:
    await actions.new_context(app, await _topic(app, message))


async def cmd_project(message: Message, command: CommandObject, app) -> None:
    await actions.project_topic(app, await _topic(app, message), command.args or "")


async def cmd_rename(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    if not (command.args or "").strip():
        await actions.send_to_topic(app, topic, texts.RENAME_USAGE)
        return
    await actions.rename_topic(app, topic, command.args.strip())


async def cmd_soul(message: Message, command: CommandObject, app) -> None:
    await actions.set_soul(app, await _topic(app, message), command.args or "")


async def cmd_files(message: Message, app) -> None:
    topic = await _topic(app, message)
    await actions.send_to_topic(app, topic, texts.files_list(await app.inbox.list_recent(topic["id"])))


async def cmd_usage(message: Message, app) -> None:
    await actions.usage_card(app, await _topic(app, message))


# ------------------------------------------------------------------ turns

async def any_message(message: Message, app) -> None:
    """Everything that is not a bridge command goes through the batcher (PROJECT_SPEC 4.4)."""
    topic = await _topic(app, message)
    if message.text and await app.prompts.consume_text(topic, message.text):
        return   # the text answered a card that asked for it (deny comment, custom answer, plan rework)
    app.batcher.add(topic, message)


async def edited_message(message: Message, app) -> None:
    if not (message.text or message.caption):
        return
    topic = await _topic(app, message)
    app.batcher.add(topic, message, flag="edited")


async def on_generation_stopped(event: MessageGenerationStopped, app) -> None:
    topic = await app.topics.get(TopicRef(event.chat.id, event.message_thread_id))
    rt = app.runtimes.peek(topic["id"]) if topic else None
    if rt is not None:
        await rt.cancel()


async def on_callback_query(cq: CallbackQuery, app) -> None:
    await on_callback(cq, app)


def build_router() -> Router:
    """A fresh Router per Dispatcher: aiogram routers cannot be attached twice."""
    router = Router(name="bridge")
    router.message.register(cmd_help, Command("help", "start"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_new, Command("new", "clear"))
    router.message.register(cmd_project, Command("project"))
    router.message.register(cmd_rename, Command("rename"))
    router.message.register(cmd_soul, Command("soul"))
    router.message.register(cmd_files, Command("files"))
    router.message.register(cmd_usage, Command("usage"))
    router.message.register(any_message, CONTENT_FILTER)
    router.edited_message.register(edited_message, CONTENT_FILTER)
    router.stopped_message_generation.register(on_generation_stopped)
    router.callback_query.register(on_callback_query)
    return router
