"""The single door for outgoing Telegram calls: everything goes through the outbox."""
from __future__ import annotations

from aiogram.methods import SendMessage, TelegramMethod

from app.store.repos import Store


class TelegramSender:
    def __init__(self, store: Store, wake: callable):
        self.store = store
        self._wake = wake

    async def enqueue(self, topic_key: str, method: TelegramMethod) -> int:
        payload = method.model_dump(exclude_none=True, exclude_defaults=True, mode="json")
        row_id = await self.store.outbox.enqueue(topic_key, type(method).__name__, payload)
        self._wake()
        return row_id

    async def send_text(self, chat_id: int, thread_id: int | None, text: str, *,
                        reply_to_message_id: int | None = None) -> int:
        method = SendMessage(
            chat_id=chat_id, text=text, message_thread_id=thread_id,
            reply_parameters={"message_id": reply_to_message_id} if reply_to_message_id else None)
        return await self.enqueue(f"{chat_id}:{thread_id or 0}", method)
