"""Inbox: downloaded and generated files per topic, with collision-safe names and TTL cleanup."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import settings
from app.ingest.classify import sanitize_filename

log = logging.getLogger(__name__)


class InboxService:
    def __init__(self, app):
        self.app = app

    def _dir(self, topic_id: int) -> Path:
        d = Path(settings.INBOX_DIR) / str(topic_id) / datetime.now().strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def unique_path(directory: Path, name: str) -> Path:
        candidate = directory / name
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        n = 1
        while candidate.exists():
            candidate = directory / (f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}")
            n += 1
        return candidate

    async def download(self, topic_id: int, file_id: str, name: str, kind: str) -> Path:
        """Download a Telegram file into the topic's inbox; returns the local path."""
        path = self.unique_path(self._dir(topic_id), sanitize_filename(name))
        await self.app.bot.download(file_id, destination=str(path))
        size = path.stat().st_size if path.exists() else None
        await self.app.store.inbox.add(topic_id, str(path), file_id, kind, size)
        return path

    async def list_recent(self, topic_id: int, limit: int = 10) -> list[dict]:
        return await self.app.store.inbox.list_recent(topic_id, limit)

    async def cleanup(self, ttl_days: float | None = None) -> int:
        """Delete inbox files older than the TTL (files on disk and their rows)."""
        ttl = settings.INBOX_TTL_DAYS if ttl_days is None else ttl_days
        cutoff = time.time() - ttl * 86400
        removed = 0
        for row in await self.app.store.inbox.older_than(cutoff):
            try:
                if os.path.exists(row["path"]):
                    os.remove(row["path"])
                removed += 1
            except OSError as e:
                log.warning("inbox cleanup: cannot remove %s: %s", row["path"], e)
            await self.app.store.inbox.delete(row["id"])
        if removed:
            log.info("inbox cleanup: removed %d files", removed)
        return removed
