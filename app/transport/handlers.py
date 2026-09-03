"""Command and message handlers. `app` is injected from dispatcher workflow data."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core.topics import TopicRef
from app.transport import texts



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


async def cmd_help(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.HELP)


async def cmd_whoami(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id,
                               texts.whoami(message.from_user.id, ref.chat_id, ref.thread_id))


async def cmd_topics(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.topics_list(await app.topics.list_all()))


async def cmd_status(message: Message, app) -> None:
    ref = topic_ref(message)
    await _remember_user(app, message)
    topic = await app.topics.get_or_create(ref, topic_title(message))
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.status(topic))


async def any_message(message: Message, app) -> None:
    """Phase 1 placeholder: registers the topic; turns arrive in phase 2."""
    ref = topic_ref(message)
    await _remember_user(app, message)
    topic = await app.topics.get_or_create(ref, topic_title(message))
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.TURNS_NOT_YET.format(cwd=topic["cwd"]))


def build_router() -> Router:
    """A fresh Router per Dispatcher: aiogram routers cannot be attached twice."""
    router = Router(name="phase1")
    router.message.register(cmd_help, Command("help", "start"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(cmd_topics, Command("topics"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(
        any_message, F.text | F.caption | F.photo | F.document | F.voice | F.audio | F.video_note | F.video)
    return router
