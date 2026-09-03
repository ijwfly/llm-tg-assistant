"""Recording aiogram session: captures every outgoing call and returns aiogram's own objects."""
from __future__ import annotations

import itertools
import typing
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, File, ForumTopic, Message, User

from app.transport.sender import _strip_none


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []          # calls Telegram accepted
        self.failed_calls: list[tuple[str, dict]] = []   # calls that hit an injected failure
        self._fail: dict[str, list[Exception]] = {}
        self._message_ids = itertools.count(1000)
        self.files: dict[str, bytes] = {}   # file_id -> bytes served by getFile/download
        self._thread_ids = itertools.count(100)

    def fail_next(self, method_name: str, exc: Exception) -> None:
        """Inject `exc` into the next call of `method_name` (e.g. "SendMessage")."""
        self._fail.setdefault(method_name, []).append(exc)

    async def close(self) -> None:
        pass

    async def stream_content(self, url: str, *args, **kwargs):
        file_id = url.rsplit("/", 1)[-1]
        yield self.files.get(file_id, f"fake-bytes-{file_id}".encode())

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        name = type(method).__name__
        payload = _strip_none(method.model_dump(exclude_none=True, mode="json",
                                                fallback=lambda v: getattr(v, "path", None)))
        queue = self._fail.get(name)
        if queue:
            self.failed_calls.append((name, payload))
            raise queue.pop(0)
        self.calls.append((name, payload))
        return self._build_result(bot, method)

    def _build_result(self, bot: Bot, method: TelegramMethod):
        returning = method.__returning__
        candidates = set(typing.get_args(returning)) or {returning}
        if Message in candidates:
            chat_id = getattr(method, "chat_id", 0)
            return Message(
                message_id=next(self._message_ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
                text=getattr(method, "text", None),
                message_thread_id=getattr(method, "message_thread_id", None),
            )
        if ForumTopic in candidates:
            return ForumTopic(message_thread_id=next(self._thread_ids), name=method.name,
                              icon_color=method.icon_color or 0x6FB9F0)
        if File in candidates:
            return File(file_id=method.file_id, file_unique_id="u" + method.file_id,
                        file_size=len(self.files.get(method.file_id, b"x" * 10)), file_path=method.file_id)
        if User in candidates:
            return User(id=bot.id, is_bot=True, first_name="Test Bot", username="testbot")
        if bool in candidates:
            return True
        if typing.get_origin(returning) is list:
            return []
        raise NotImplementedError(f"RecordingSession: no result builder for {name} -> {returning}")
