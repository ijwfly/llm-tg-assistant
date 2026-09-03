"""Unix-socket endpoint of the daemon for the bridge MCP server (one JSON line in, one out)."""
from __future__ import annotations

import asyncio
import json
import logging
import os

import settings

log = logging.getLogger(__name__)


class BridgeSocket:
    def __init__(self, app):
        self.app = app
        self.server: asyncio.AbstractServer | None = None
        self.path: str | None = None

    async def start(self) -> None:
        self.path = settings.BRIDGE_SOCKET
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.server = await asyncio.start_unix_server(self._serve, path=self.path)
        os.chmod(self.path, 0o600)
        log.info("bridge socket listening on %s", self.path)

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.path and os.path.exists(self.path):
            os.unlink(self.path)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                request = {}
            decision = await self.app.prompts.handle(request, closed=reader)
            writer.write((json.dumps(decision, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            raise
        except Exception:
            log.exception("bridge socket request failed")
            try:
                writer.write(b'{"behavior": "deny", "message": "Telegram bridge internal error"}\n')
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
