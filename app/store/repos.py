"""Repositories: thin, explicit SQL over the Database wrapper."""
from __future__ import annotations

import uuid
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

    async def settings(self, tg_id: int) -> dict:
        row = await self.db.fetchval("SELECT settings FROM users WHERE tg_id = $1", tg_id)
        return dict(row or {})

    async def update_settings(self, tg_id: int, **fields: Any) -> dict:
        return dict(await self.db.fetchval(
            "UPDATE users SET settings = settings || $2::jsonb WHERE tg_id = $1 RETURNING settings", tg_id, fields) or {})


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
            """INSERT INTO topics (chat_id, thread_id, title, cwd, permission_mode, model, effort, session_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (chat_id, COALESCE(thread_id, 0)) DO UPDATE
                 SET last_activity_at = now(),
                     title = COALESCE(EXCLUDED.title, topics.title)
               RETURNING *""", chat_id, thread_id, title, cwd, permission_mode, model, effort, uuid.uuid4()))

    async def list_all(self) -> list[dict]:
        return [dict(r) for r in await self.db.fetch("SELECT * FROM topics ORDER BY last_activity_at DESC")]

    async def get_by_id(self, topic_id: int) -> dict | None:
        return _row(await self.db.fetchrow("SELECT * FROM topics WHERE id = $1", topic_id))

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
    topic_id: int | None = None
    turn_id: int | None = None
    role: str | None = None


class TurnsRepo:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, topic_id: int, prompt: list[dict]) -> dict:
        return _row(await self.db.fetchrow(
            "INSERT INTO turns (topic_id, prompt) VALUES ($1, $2) RETURNING *", topic_id, prompt))

    async def set_running(self, turn_id: int) -> None:
        await self.db.execute("UPDATE turns SET status = 'running', started_at = now() WHERE id = $1", turn_id)

    async def finish(self, turn_id: int, *, status: str, result_subtype: str | None = None,
                     duration_ms: int | None = None, num_turns: int | None = None, cost_usd: float | None = None,
                     usage: dict | None = None, error: str | None = None) -> None:
        await self.db.execute(
            """UPDATE turns SET status = $2, result_subtype = $3, duration_ms = $4, num_turns = $5,
                                cost_usd = $6, usage = $7, error = $8, finished_at = now()
               WHERE id = $1""", turn_id, status, result_subtype, duration_ms, num_turns, cost_usd, usage, error)

    async def get(self, turn_id: int) -> dict | None:
        return _row(await self.db.fetchrow("SELECT * FROM turns WHERE id = $1", turn_id))

    async def last_for_topic(self, topic_id: int) -> dict | None:
        return _row(await self.db.fetchrow(
            "SELECT * FROM turns WHERE topic_id = $1 ORDER BY id DESC LIMIT 1", topic_id))


# The head of every topic's queue (oldest pending row per topic_key). Delivery order inside a
# topic must hold even when the head is parked by a retry, so due-ness is filtered *after* the
# head is chosen, never before.
HEAD_OF_QUEUE = """
    SELECT * FROM (
        SELECT DISTINCT ON (topic_key) id, topic_key, method, payload, attempts, created_at, next_attempt_at,
                                       topic_id, turn_id, role
        FROM outbox
        WHERE status = 'pending' AND NOT (topic_key = ANY($1::text[]))
        ORDER BY topic_key, id
    ) heads"""


class OutboxRepo:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(self, topic_key: str, method: str, payload: dict, *, topic_id: int | None = None,
                      turn_id: int | None = None, role: str | None = None) -> int:
        return await self.db.fetchval(
            """INSERT INTO outbox (topic_key, method, payload, topic_id, turn_id, role)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            topic_key, method, payload, topic_id, turn_id, role)

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


class StagingRepo:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, topic_id: int, kind: str, order_group: int, payload: dict, tg_message_id: int | None) -> int:
        return await self.db.fetchval(
            """INSERT INTO staging_items (topic_id, kind, order_group, payload, tg_message_id)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""", topic_id, kind, order_group, payload, tg_message_id)

    async def take_all(self, topic_id: int) -> list[dict]:
        """Return the topic's staged items in consumption order and delete them."""
        rows = await self.db.fetch(
            "DELETE FROM staging_items WHERE topic_id = $1 RETURNING *", topic_id)
        return sorted((dict(r) for r in rows), key=lambda r: (r["order_group"], r["id"]))

    async def count(self, topic_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM staging_items WHERE topic_id = $1", topic_id)

    async def clear(self, topic_id: int) -> None:
        await self.db.execute("DELETE FROM staging_items WHERE topic_id = $1", topic_id)


class InboxRepo:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, topic_id: int | None, path: str, tg_file_id: str | None, kind: str, size: int | None) -> int:
        return await self.db.fetchval(
            "INSERT INTO inbox_files (topic_id, path, tg_file_id, kind, size) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            topic_id, path, tg_file_id, kind, size)

    async def list_recent(self, topic_id: int, limit: int = 10) -> list[dict]:
        return [dict(r) for r in await self.db.fetch(
            "SELECT * FROM inbox_files WHERE topic_id = $1 ORDER BY id DESC LIMIT $2", topic_id, limit)]

    async def older_than(self, cutoff_epoch: float) -> list[dict]:
        return [dict(r) for r in await self.db.fetch(
            "SELECT * FROM inbox_files WHERE created_at < to_timestamp($1)", cutoff_epoch)]

    async def delete(self, row_id: int) -> None:
        await self.db.execute("DELETE FROM inbox_files WHERE id = $1", row_id)

    async def touch_created(self, row_id: int, epoch: float) -> None:   # tests: age a row
        await self.db.execute("UPDATE inbox_files SET created_at = to_timestamp($2) WHERE id = $1", row_id, epoch)


class Store:
    def __init__(self, db: Database):
        self.db = db
        self.users = UsersRepo(db)
        self.topics = TopicsRepo(db)
        self.outbox = OutboxRepo(db)
        self.turns = TurnsRepo(db)
        self.staging = StagingRepo(db)
        self.inbox = InboxRepo(db)
        self.updates = UpdatesRepo(db)
        self.links = MessageLinksRepo(db)
