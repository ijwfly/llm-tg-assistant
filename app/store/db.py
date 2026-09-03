"""asyncpg pool wrapper and idempotent SQL migrations."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, min_size: int = 1, max_size: int = 10) -> "Database":
        pool = await asyncpg.create_pool(url, min_size=min_size, max_size=max_size, init=_init_connection)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self, directory: Path = MIGRATIONS_DIR) -> list[str]:
        """Apply every NNNN_*.sql in order. Files are idempotent, so re-applying is safe."""
        applied = []
        async with self.pool.acquire() as conn:
            for path in sorted(directory.glob("*.sql")):
                await conn.execute(path.read_text())
                applied.append(path.name)
        log.info("migrations applied: %s", applied)
        return applied

    # thin helpers
    async def fetch(self, query: str, *args):
        return await self.pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        return await self.pool.fetchval(query, *args)

    async def execute(self, query: str, *args):
        return await self.pool.execute(query, *args)
