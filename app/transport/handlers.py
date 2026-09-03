"""Command and message handlers. `app` is injected from dispatcher workflow data."""
from __future__ import annotations

import os
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, MessageGenerationStopped

import settings
from app.core.runtime import QueueFull, TurnRequest
from app.core.topics import TopicRef
from app.transport import texts

QUOTE_LIMIT = 700


def topic_ref(message: Message) -> TopicRef:
    thread = message.message_thread_id if message.is_topic_message else None
    return TopicRef(message.chat.id, thread)


def topic_title(message: Message) -> str | None:
    if message.chat.type == "private" and not message.is_topic_message:
        return None
    if message.is_topic_message and message.reply_to_message and message.reply_to_message.forum_topic_created:
        return message.reply_to_message.forum_topic_created.name
    return message.chat.title


async def _remember_user(app, message: Message) -> None:
    u = message.from_user
    if u is not None:
        await app.store.users.upsert(u.id, u.full_name, u.username)


async def _topic(app, message: Message) -> dict:
    await _remember_user(app, message)
    return await app.topics.get_or_create(topic_ref(message), topic_title(message))


def reply_quote(message: Message, bot_id: int) -> str | None:
    reply = message.reply_to_message
    if reply is None or reply.forum_topic_created is not None:
        return None
    quoted = message.quote.text if message.quote else (reply.text or reply.caption)
    if not quoted:
        return None
    quoted = quoted[:QUOTE_LIMIT]
    who = "твой ответ" if reply.from_user and reply.from_user.id == bot_id else "сообщение"
    return f"[в ответ на {who}: «{quoted}»]"


def build_turn_text(message: Message, bot_id: int) -> str:
    parts = []
    quote = reply_quote(message, bot_id)
    if quote:
        parts.append(quote)
    body = message.text or message.caption or ""
    if body:
        parts.append(body)
    return "\n\n".join(parts)


# ------------------------------------------------------------------ commands

async def cmd_help(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.HELP)


async def cmd_whoami(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id,
                               texts.whoami(message.from_user.id, ref.chat_id, ref.thread_id))


async def cmd_topics(message: Message, app) -> None:
    ref = topic_ref(message)
    topics = await app.topics.list_all()
    states = {t["id"]: rt.status() for t in topics if (rt := app.runtimes.peek(t["id"]))}
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.topics_list(topics, states))


async def cmd_status(message: Message, app) -> None:
    topic = await _topic(app, message)
    rt = app.runtimes.peek(topic["id"])
    await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.status(topic, rt.status() if rt else None),
                               topic_id=topic["id"])


async def cmd_new(message: Message, app) -> None:
    topic = await _topic(app, message)
    await app.runtimes.get(topic).restart_context()
    await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.NEW_CONTEXT, topic_id=topic["id"])


async def cmd_stop(message: Message, app) -> None:
    topic = await _topic(app, message)
    await app.runtimes.get(topic).stop_process()
    await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.PROCESS_STOPPED, topic_id=topic["id"])


async def cmd_cancel(message: Message, app) -> None:
    ref = topic_ref(message)
    topic = await app.topics.get(ref)
    rt = app.runtimes.peek(topic["id"]) if topic else None
    if rt is None or not await rt.cancel():
        await app.sender.send_text(ref.chat_id, ref.thread_id, texts.NOTHING_TO_CANCEL)


async def cmd_retry(message: Message, app) -> None:
    topic = await _topic(app, message)
    last = await app.store.turns.last_for_topic(topic["id"])
    if last is None:
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.NOTHING_TO_RETRY, topic_id=topic["id"])
        return
    await _submit(app, topic, TurnRequest(content=last["prompt"]))


def resolve_cwd(raw: str) -> tuple[str | None, str | None]:
    """(path, error_text). The path must exist and live inside WORK_ROOT."""
    path = Path(os.path.expanduser(raw.strip())).resolve()
    root = Path(settings.WORK_ROOT).resolve()
    if not path.is_dir():
        return None, texts.CD_NO_DIR.format(path=path)
    if path != root and root not in path.parents:
        return None, texts.CD_OUTSIDE.format(path=path, root=root)
    return str(path), None


async def _change_dir(app, topic: dict, raw: str) -> None:
    path, error = resolve_cwd(raw)
    if error:
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], error, topic_id=topic["id"])
        return
    await app.runtimes.get(topic).restart_context(cwd=path)
    await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.CD_OK.format(path=path), topic_id=topic["id"])


async def cmd_cd(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    if not command.args:
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.CD_USAGE, topic_id=topic["id"])
        return
    await _change_dir(app, topic, command.args)


async def cmd_go(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    alias = (command.args or "").strip()
    if not alias:
        text = texts.go_list(settings.PROJECTS) if settings.PROJECTS else texts.GO_EMPTY
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], text, topic_id=topic["id"])
        return
    if alias not in settings.PROJECTS:
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.GO_UNKNOWN.format(alias=alias),
                                   topic_id=topic["id"])
        return
    await _change_dir(app, topic, settings.PROJECTS[alias])


# ------------------------------------------------------------------ turns

async def _submit(app, topic: dict, request: TurnRequest) -> None:
    rt = app.runtimes.get(topic)
    try:
        busy = await rt.submit(request)
    except QueueFull:
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.QUEUE_FULL, topic_id=topic["id"])
        return
    if busy and rt.current is not None and not rt.current.hint_sent:
        rt.current.hint_sent = True
        await app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.QUEUE_HINT, topic_id=topic["id"])


async def any_message(message: Message, app) -> None:
    text = build_turn_text(message, app.bot.id)
    if not text.strip():
        return
    topic = await _topic(app, message)
    await app.store.links.link(message.chat.id, message.message_id, topic["id"], "user")
    await _submit(app, topic, TurnRequest(content=[{"type": "text", "text": text}]))


async def on_generation_stopped(event: MessageGenerationStopped, app) -> None:
    topic = await app.topics.get(TopicRef(event.chat.id, event.message_thread_id))
    rt = app.runtimes.peek(topic["id"]) if topic else None
    if rt is not None:
        await rt.cancel()


def build_router() -> Router:
    """A fresh Router per Dispatcher: aiogram routers cannot be attached twice."""
    router = Router(name="bridge")
    router.message.register(cmd_help, Command("help", "start"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(cmd_topics, Command("topics"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_new, Command("new", "clear"))
    router.message.register(cmd_stop, Command("stop"))
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(cmd_retry, Command("retry"))
    router.message.register(cmd_cd, Command("cd"))
    router.message.register(cmd_go, Command("go"))
    router.message.register(any_message, F.text | F.caption)
    router.stopped_message_generation.register(on_generation_stopped)
    return router
