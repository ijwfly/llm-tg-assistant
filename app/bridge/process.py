"""A long-lived `claude -p` process speaking stream-json on stdin/stdout."""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
import signal
import time
from typing import AsyncIterator

import settings

log = logging.getLogger(__name__)

STDOUT_LIMIT = 32 * 1024 * 1024
_SECRET_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")  # bot-token shaped strings


class ClaudeProcess:
    def __init__(self, argv: list[str], cwd: str, env: dict[str, str]):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None
        self.started_at = 0.0
        self.stderr_tail: collections.deque[str] = collections.deque(maxlen=12)
        self._stderr_task: asyncio.Task | None = None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode if self.proc else None

    @property
    def uptime(self) -> float:
        return time.monotonic() - self.started_at if self.proc else 0.0

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.argv, cwd=self.cwd, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=STDOUT_LIMIT)
        self.started_at = time.monotonic()
        self._stderr_task = asyncio.create_task(self._pump_stderr(), name=f"claude-stderr-{self.proc.pid}")
        log.info("claude started pid=%s cwd=%s", self.proc.pid, self.cwd)

    async def _pump_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = _SECRET_RE.sub("<redacted>", line.decode(errors="replace").rstrip())
            self.stderr_tail.append(text)
            log.debug("claude[%s] stderr: %s", self.proc.pid, text)

    async def send(self, message: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()

    async def send_user(self, content) -> None:
        await self.send({"type": "user", "message": {"role": "user", "content": content}})

    async def events(self) -> AsyncIterator[dict]:
        """Yields parsed stdout events until EOF. Non-JSON lines are logged and skipped."""
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                return
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("claude[%s] non-json stdout: %r", self.pid, line[:200])

    def interrupt(self) -> None:
        """SIGINT ends the current turn; the CLI then exits on its own."""
        if self.alive:
            self.proc.send_signal(signal.SIGINT)

    async def stop(self, grace: float | None = None) -> int | None:
        """Graceful stop: close stdin, wait, SIGTERM, wait, SIGKILL."""
        if self.proc is None:
            return None
        grace = settings.PROCESS_STOP_GRACE_SECS if grace is None else grace
        if self.alive:
            try:
                if self.proc.stdin and not self.proc.stdin.is_closing():
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=grace)
            except asyncio.TimeoutError:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
        if self._stderr_task:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._stderr_task.cancel()
        log.info("claude stopped pid=%s code=%s", self.pid, self.returncode)
        return self.returncode
