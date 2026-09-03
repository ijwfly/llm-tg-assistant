"""Topic = one Claude Code session bound to (chat_id, thread_id)."""
from __future__ import annotations

from dataclasses import dataclass

import settings
from app.store.repos import Store


@dataclass(frozen=True)
class TopicRef:
    chat_id: int
    thread_id: int | None

    @property
    def key(self) -> str:
        return f"{self.chat_id}:{self.thread_id or 0}"


class TopicService:
    def __init__(self, store: Store):
        self.store = store

    async def get(self, ref: TopicRef) -> dict | None:
        return await self.store.topics.get(ref.chat_id, ref.thread_id)

    async def get_or_create(self, ref: TopicRef, title: str | None = None) -> dict:
        return await self.store.topics.get_or_create(
            ref.chat_id, ref.thread_id,
            cwd=settings.DEFAULT_CWD, title=title,
            permission_mode=settings.DEFAULT_PERMISSION_MODE,
            model=settings.DEFAULT_MODEL, effort=settings.DEFAULT_EFFORT)

    async def list_all(self) -> list[dict]:
        return await self.store.topics.list_all()
