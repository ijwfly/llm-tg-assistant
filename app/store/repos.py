"""Repositories: thin, explicit SQL over the Database wrapper."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.store.db import Database


def _row(r) -> dict | None:
    return dict(r) if r is not None else None


class UsersRepo:
    def __init__(self, db: Database):
        self.db = db

    async def upsert(self, tg_id: int, name: str | None, username: str | None) -> dict:
        return _row(await self.db.fetchrow(
            """INSERT INTO users (tg_id, name, username) VALUES ($1, $2, $3)
               ON CONFLICT (tg_id) DO UPDATE SET name = EXCLUDED.name, username = EXCLUDED.username
               RETURNING *""", tg_id, name, username))

    async def get(self, tg_id: int) -> dict | None:
        return _row(await self.db.fetchrow("SELECT * FROM users WHERE tg_id = $1", tg_id))


class TopicsRepo:
    def __init__(self, db: Database):
        self.db = db

    async def get(self, chat_id: int, thread_id: int | None) -> dict | None:
        return _row(await self.db.fetchrow(
            "SELECT * FROM topics WHERE chat_id = $1 AND COALESCE(thread_id, 0) = COALESCE($2, 0)",
            chat_id, thread_id))

    async def get_or_create(self, chat_id: int, thread_id: int | None, *, cwd: str, title: str | None,
                            permission_mode: str | None, model: str | None, effort: str | None) -> dict:
        return _row(await self.db.fetchrow(
            """INSERT INTO topics (chat_id, thread_id, title, cwd, permission_mode, model, effort)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (chat_id, COALESCE(thread_id, 0)) DO UPDATE
                 SET last_activity_at = now(),
                     title = COALESCE(EXCLUDED.title, topics.title)
               RETURNING *""", chat_id, thread_id, title, cwd, permission_mode, model, effort))

    async def list_all(self) -> list[dict]:
        return [dict(r) for r in await self.db.fetch("SELECT * FROM topics ORDER BY last_activity_at DESC")]

    async def update(self, topic_id: int, **fields: Any) -> dict:
        if not fields:
            return _row(await self.db.fetchrow("SELECT * FROM topics WHERE id = $1", topic_id))
        cols = list(fields)
        sets = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
        return _row(await self.db.fetchrow(
            f"UPDATE topics SET {sets}, last_activity_at = now() WHERE id = $1 RETURNING *",
            topic_id, *[fields[c] for c in cols]))


@dataclass
class OutboxRow:
    id: int
    topic_key: str
    method: str
    payload: dict
    attempts: int
    created_at: datetime


# The head of every topic's queue (oldest pending row per topic_key). Delivery order inside a
# topic must hold even when the head is parked by a retry, so due-ness is filtered *after* the
# head is chosen, never before.
HEAD_OF_QUEUE = """
    SELECT * FROM (
        SELECT DISTINCT ON (topic_key) id, topic_key, method, payload, attempts, created_at, next_attempt_at
        FROM outbox
        WHERE status = 'pending' AND NOT (topic_key = ANY($1::text[]))
        ORDER BY topic_key, id
    ) heads"""


class OutboxRepo:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(self, topic_key: str, method: str, payload: dict) -> int:
        return await self.db.fetchval(
            "INSERT INTO outbox (topic_key, method, payload) VALUES ($1, $2, $3) RETURNING id",
            topic_key, method, payload)

    async def next_batch(self, exclude_keys: set[str]) -> list[OutboxRow]:
        """One due pending row per topic_key, oldest first, skipping keys currently in flight."""
        rows = await self.db.fetch(HEAD_OF_QUEUE + " WHERE next_attempt_at <= now()", list(exclude_keys))
        return [OutboxRow(**{k: r[k] for k in OutboxRow.__dataclass_fields__}) for r in rows]

    async def has_due_pending(self, exclude_keys: set[str]) -> bool:
        return bool(await self.db.fetchval(
            HEAD_OF_QUEUE + " WHERE next_attempt_at <= now() LIMIT 1", list(exclude_keys)))

    async def pending_count(self) -> int:
        return await self.db.fetchval("SELECT count(*) FROM outbox WHERE status = 'pending'")

    async def mark_delivered(self, row_id: int, message_id: int | None) -> None:
        await self.db.execute(
            "UPDATE outbox SET status = 'delivered', delivered_at = now(), delivered_message_id = $2 WHERE id = $1",
            row_id, message_id)

    async def reschedule(self, row_id: int, delay_secs: float, error: str, count_attempt: bool) -> None:
        await self.db.execute(
            """UPDATE outbox SET next_attempt_at = now() + $2 * interval '1 second',
                                 attempts = attempts + $3, last_error = $4
               WHERE id = $1""", row_id, float(delay_secs), 1 if count_attempt else 0, error[:2000])

    async def mark_failed(self, row_id: int, error: str) -> None:
        await self.db.execute(
            "UPDATE outbox SET status = 'failed', last_error = $2 WHERE id = $1", row_id, error[:2000])

    async def get(self, row_id: int) -> dict | None:
        return _row(await self.db.fetchrow("SELECT * FROM outbox WHERE id = $1", row_id))


class UpdatesRepo:
    def __init__(self, db: Database):
        self.db = db

    async def mark_processed(self, update_id: int) -> bool:
        """True if this update_id was not seen before."""
        return bool(await self.db.fetchval(
            "INSERT INTO processed_updates (update_id) VALUES ($1) ON CONFLICT DO NOTHING RETURNING update_id",
            update_id))

    async def cleanup(self, older_than: timedelta = timedelta(days=7)) -> None:
        await self.db.execute("DELETE FROM processed_updates WHERE at < $1",
                              datetime.now(timezone.utc) - older_than)


class MessageLinksRepo:
    def __init__(self, db: Database):
        self.db = db

    async def link(self, chat_id: int, tg_message_id: int, topic_id: int | None, role: str,
                   turn_id: int | None = None) -> None:
        await self.db.execute(
            """INSERT INTO message_links (chat_id, tg_message_id, topic_id, turn_id, role)
               VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""",
            chat_id, tg_message_id, topic_id, turn_id, role)

    async def get(self, chat_id: int, tg_message_id: int) -> dict | None:
        return _row(await self.db.fetchrow(
            "SELECT * FROM message_links WHERE chat_id = $1 AND tg_message_id = $2", chat_id, tg_message_id))


class Store:
    def __init__(self, db: Database):
        self.db = db
        self.users = UsersRepo(db)
        self.topics = TopicsRepo(db)
        self.outbox = OutboxRepo(db)
        self.updates = UpdatesRepo(db)
        self.links = MessageLinksRepo(db)
