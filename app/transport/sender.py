"""The single door for outgoing Telegram calls: everything goes through the outbox."""
from __future__ import annotations

from aiogram.methods import SendMessage, SendRichMessage, TelegramMethod
from aiogram.types import InputRichMessage

from app.render.markdown import RICH_LIMIT, split_text
from app.store.repos import Store


class TelegramSender:
    def __init__(self, store: Store, wake: callable):
        self.store = store
        self._wake = wake

    async def enqueue(self, topic_key: str, method: TelegramMethod, *, topic_id: int | None = None,
                      turn_id: int | None = None, role: str | None = None) -> int:
        payload = method.model_dump(exclude_none=True, exclude_defaults=True, mode="json")
        row_id = await self.store.outbox.enqueue(topic_key, type(method).__name__, payload,
                                                 topic_id=topic_id, turn_id=turn_id, role=role)
        self._wake()
        return row_id

    async def send_text(self, chat_id: int, thread_id: int | None, text: str, *,
                        reply_to_message_id: int | None = None, topic_id: int | None = None,
                        turn_id: int | None = None, role: str | None = "bot") -> int:
        method = SendMessage(
            chat_id=chat_id, text=text, message_thread_id=thread_id,
            reply_parameters={"message_id": reply_to_message_id} if reply_to_message_id else None)
        return await self.enqueue(f"{chat_id}:{thread_id or 0}", method, topic_id=topic_id, turn_id=turn_id, role=role)

    async def send_markdown(self, chat_id: int, thread_id: int | None, markdown: str, *,
                            reply_to_message_id: int | None = None, topic_id: int | None = None,
                            turn_id: int | None = None, role: str | None = "assistant") -> list[int]:
        """Rich message(s); the outbox worker falls back to plain text if Telegram rejects the markup."""
        ids = []
        for chunk in split_text(markdown, RICH_LIMIT):
            method = SendRichMessage(
                chat_id=chat_id, message_thread_id=thread_id, rich_message=InputRichMessage(markdown=chunk),
                reply_parameters={"message_id": reply_to_message_id} if reply_to_message_id else None)
            ids.append(await self.enqueue(f"{chat_id}:{thread_id or 0}", method,
                                          topic_id=topic_id, turn_id=turn_id, role=role))
            reply_to_message_id = None
        return ids
