"""The single door for outgoing Telegram calls: everything goes through the outbox."""
from __future__ import annotations

from aiogram.methods import DeleteMessage, EditMessageText, SendMessage, SendRichMessage, SetMessageReaction, TelegramMethod
from aiogram.types import InputRichMessage, ReactionTypeEmoji

from app.render.markdown import RICH_LIMIT, split_markdown
from app.store.repos import Store

FILE_PREFIX = "file://"   # outbox payloads carry local files as "file://<path>"; the worker opens them


def _strip_none(value):
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def dump_method(method: TelegramMethod) -> dict:
    """JSON payload of an aiogram method: drops aiogram's `Default` sentinels (unserializable) but
    keeps real defaults such as pydantic discriminators (`type: "emoji"`)."""
    raw = method.model_dump(exclude_none=True, mode="json", fallback=lambda v: None)
    return _strip_none(raw)


class TelegramSender:
    def __init__(self, store: Store, wake: callable):
        self.store = store
        self._wake = wake

    async def enqueue(self, topic_key: str, method: TelegramMethod, *, topic_id: int | None = None,
                      turn_id: int | None = None, role: str | None = None) -> int:
        payload = dump_method(method)
        return await self.enqueue_raw(topic_key, type(method).__name__, payload,
                                      topic_id=topic_id, turn_id=turn_id, role=role)

    async def enqueue_raw(self, topic_key: str, method_name: str, payload: dict, *, topic_id: int | None = None,
                          turn_id: int | None = None, role: str | None = None) -> int:
        row_id = await self.store.outbox.enqueue(topic_key, method_name, payload,
                                                 topic_id=topic_id, turn_id=turn_id, role=role)
        self._wake()
        return row_id

    @staticmethod
    def _key(chat_id: int, thread_id: int | None) -> str:
        return f"{chat_id}:{thread_id or 0}"

    async def send_text(self, chat_id: int, thread_id: int | None, text: str, *,
                        reply_to_message_id: int | None = None, reply_markup=None, topic_id: int | None = None,
                        turn_id: int | None = None, role: str | None = "bot") -> int:
        method = SendMessage(
            chat_id=chat_id, text=text, message_thread_id=thread_id, reply_markup=reply_markup,
            reply_parameters={"message_id": reply_to_message_id} if reply_to_message_id else None)
        return await self.enqueue(self._key(chat_id, thread_id), method, topic_id=topic_id, turn_id=turn_id, role=role)

    async def send_markdown(self, chat_id: int, thread_id: int | None, markdown: str, *,
                            reply_to_message_id: int | None = None, topic_id: int | None = None,
                            turn_id: int | None = None, role: str | None = "assistant") -> list[int]:
        """Rich message(s); the outbox worker falls back to plain text if Telegram rejects the markup."""
        ids = []
        for chunk in split_markdown(markdown, RICH_LIMIT):
            method = SendRichMessage(
                chat_id=chat_id, message_thread_id=thread_id, rich_message=InputRichMessage(markdown=chunk),
                reply_parameters={"message_id": reply_to_message_id} if reply_to_message_id else None)
            ids.append(await self.enqueue(self._key(chat_id, thread_id), method,
                                          topic_id=topic_id, turn_id=turn_id, role=role))
            reply_to_message_id = None
        return ids

    async def send_document(self, chat_id: int, thread_id: int | None, path: str, *, caption: str | None = None,
                            topic_id: int | None = None, turn_id: int | None = None, role: str | None = "assistant") -> int:
        payload = {"chat_id": chat_id, "document": FILE_PREFIX + path}
        if thread_id:
            payload["message_thread_id"] = thread_id
        if caption:
            payload["caption"] = caption[:1024]
        return await self.enqueue_raw(self._key(chat_id, thread_id), "SendDocument", payload,
                                      topic_id=topic_id, turn_id=turn_id, role=role)

    async def edit_text(self, chat_id: int, thread_id: int | None, message_id: int, text: str, *,
                        reply_markup=None, topic_id: int | None = None) -> int:
        method = EditMessageText(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
        return await self.enqueue(self._key(chat_id, thread_id), method, topic_id=topic_id, role="edit")

    async def delete(self, chat_id: int, thread_id: int | None, message_id: int, *, topic_id: int | None = None) -> int:
        method = DeleteMessage(chat_id=chat_id, message_id=message_id)
        return await self.enqueue(self._key(chat_id, thread_id), method, topic_id=topic_id, role="delete")

    async def react(self, chat_id: int, message_id: int, emoji: str, *, topic_id: int | None = None) -> int:
        method = SetMessageReaction(chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeEmoji(emoji=emoji)])
        return await self.enqueue(f"{chat_id}:0", method, topic_id=topic_id, role="reaction")
