"""Builders for synthetic Telegram updates fed into the real dispatcher."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

from aiogram.types import (CallbackQuery, Chat, Document, ForumTopicCreated, Message, MessageGenerationStopped,
                           MessageOriginChannel, MessageOriginUser, PhotoSize, Update, User, Voice)

_update_ids = itertools.count(1)
_message_ids = itertools.count(1)


def user(user_id: int = 1) -> User:
    return User(id=user_id, is_bot=False, first_name="Test", last_name="User", username="tester")


def chat(chat_id: int = 1, chat_type: str = "private", title: str | None = None) -> Chat:
    return Chat(id=chat_id, type=chat_type, title=title)


def message(text: str | None = None, *, user_id: int = 1, chat_id: int = 1, chat_type: str = "private",
            thread_id: int | None = None, is_topic: bool | None = None, topic_name: str | None = None,
            reply_to: Message | None = None, message_id: int | None = None, chat_title: str | None = None,
            caption: str | None = None, photo_id: str | None = None, document: tuple[str, str, int] | None = None,
            voice_id: str | None = None, forward_from: User | None = None, forward_channel: str | None = None,
            media_group_id: str | None = None, edit_date: int | None = None) -> Message:
    if is_topic is None:
        is_topic = thread_id is not None and chat_type != "private" or (thread_id is not None and topic_name is not None)
    if topic_name and reply_to is None:
        reply_to = Message(message_id=thread_id, date=datetime.now(timezone.utc),
                           chat=chat(chat_id, chat_type, chat_title),
                           forum_topic_created=ForumTopicCreated(name=topic_name, icon_color=0x6FB9F0))
    origin = None
    if forward_from is not None:
        origin = MessageOriginUser(type="user", date=datetime.now(timezone.utc), sender_user=forward_from)
    elif forward_channel is not None:
        origin = MessageOriginChannel(type="channel", date=datetime.now(timezone.utc),
                                      chat=Chat(id=-1009, type="channel", title=forward_channel), message_id=7)
    return Message(
        message_id=message_id or next(_message_ids),
        date=datetime.now(timezone.utc),
        chat=chat(chat_id, chat_type, chat_title),
        from_user=user(user_id),
        text=text,
        caption=caption,
        message_thread_id=thread_id,
        is_topic_message=True if is_topic else None,
        reply_to_message=reply_to,
        photo=[PhotoSize(file_id=photo_id + "_s", file_unique_id="s", width=90, height=90, file_size=1000),
               PhotoSize(file_id=photo_id, file_unique_id="l", width=1280, height=960, file_size=90000)] if photo_id else None,
        document=Document(file_id=document[0], file_unique_id="d", file_name=document[1], file_size=document[2],
                          mime_type="application/octet-stream") if document else None,
        voice=Voice(file_id=voice_id, file_unique_id="v", duration=3, file_size=5000) if voice_id else None,
        forward_origin=origin,
        media_group_id=media_group_id,
        edit_date=edit_date,
    )


def text_update(text: str, *, update_id: int | None = None, **kwargs) -> Update:
    return Update(update_id=update_id or next(_update_ids), message=message(text, **kwargs))


def message_update(**kwargs) -> Update:
    update_id = kwargs.pop("update_id", None)
    return Update(update_id=update_id or next(_update_ids), message=message(**kwargs))


def edited_update(text: str, *, message_id: int, **kwargs) -> Update:
    return Update(update_id=next(_update_ids), message=None,
                  edited_message=message(text, message_id=message_id, edit_date=1_700_000_000, **kwargs))


def callback_update(data: str, *, user_id: int = 1, chat_id: int = 1, chat_type: str = "private",
                    message_id: int = 500, update_id: int | None = None) -> Update:
    msg = Message(message_id=message_id, date=datetime.now(timezone.utc), chat=chat(chat_id, chat_type),
                  from_user=User(id=0, is_bot=True, first_name="bot"), text="card")
    cq = CallbackQuery(id=str(next(_update_ids)), from_user=user(user_id), chat_instance="ci", data=data, message=msg)
    return Update(update_id=update_id or next(_update_ids), callback_query=cq)


def stopped_update(draft_id: int, *, chat_id: int = 1, thread_id: int | None = None, update_id: int | None = None) -> Update:
    ev = MessageGenerationStopped(chat=chat(chat_id, "private"), draft_id=draft_id, message_thread_id=thread_id)
    return Update(update_id=update_id or next(_update_ids), stopped_message_generation=ev)
