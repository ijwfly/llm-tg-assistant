"""Per-topic runtime: the claude process, the turn queue and the turn loop."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import settings
from app.bridge import events as ev
from app.bridge.cli import build_argv, child_env
from app.bridge.process import ClaudeProcess
from app.transport import texts

log = logging.getLogger(__name__)


@dataclass
class TurnRequest:
    content: list[dict]                 # content blocks for the user message
    turn_id: int | None = None          # set when re-running an existing turn row (/retry creates a new one)


@dataclass
class TurnState:
    turn_id: int
    request: TurnRequest
    started: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    timed_out: bool = False
    aborted: bool = False               # daemon shutting down
    got_init: bool = False
    texts_sent: int = 0
    denials: list[str] = field(default_factory=list)
    compacted: bool = False
    compact_pre_tokens: int | None = None
    result: ev.Result | None = None
    hint_sent: bool = False


class QueueFull(Exception):
    pass


class TopicRuntime:
    def __init__(self, app, topic: dict):
        self.app = app
        self.topic_id: int = topic["id"]
        self.chat_id: int = topic["chat_id"]
        self.thread_id: int | None = topic["thread_id"]
        self.key = f"{self.chat_id}:{self.thread_id or 0}"
        self.queue: asyncio.Queue[TurnRequest] = asyncio.Queue(maxsize=settings.TURN_QUEUE_MAX)
        self.proc: ClaudeProcess | None = None
        self.current: TurnState | None = None
        self.last_turn: dict | None = None
        self._worker = asyncio.create_task(self._loop(), name=f"topic-{self.topic_id}")
        self._idle_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()   # guards process start/stop against commands

    # ------------------------------------------------------------------ public API

    async def submit(self, request: TurnRequest) -> bool:
        """Queue a turn. Returns True if a turn is already running (caller shows the hint once)."""
        busy = self.current is not None
        try:
            self.queue.put_nowait(request)
        except asyncio.QueueFull:
            raise QueueFull()
        return busy

    async def cancel(self) -> bool:
        state = self.current
        if state is None or self.proc is None or not self.proc.alive:
            return False
        state.cancelled = True
        self.proc.interrupt()
        return True

    async def stop_process(self) -> None:
        async with self._lock:
            await self._stop_process_locked()

    async def restart_context(self, *, cwd: str | None = None) -> dict:
        """New session id (and optionally a new directory). The old transcript stays on disk."""
        async with self._lock:
            await self._stop_process_locked()
            fields = {"session_id": uuid.uuid4(), "session_resumable": False}
            if cwd:
                fields["cwd"] = cwd
            return await self.app.store.topics.update(self.topic_id, **fields)

    async def shutdown(self) -> None:
        state = self.current
        if state is not None:
            state.aborted = True
            await self.app.store.turns.finish(state.turn_id, status="aborted")
            await self.app.sender.send_text(self.chat_id, self.thread_id, texts.DAEMON_STOPPED,
                                            topic_id=self.topic_id, turn_id=state.turn_id, role="verdict")
        self._worker.cancel()
        if self._idle_task:
            self._idle_task.cancel()
        async with self._lock:
            await self._stop_process_locked()

    def status(self) -> dict:
        state = self.current
        return {
            "process": (self.proc.uptime if self.proc and self.proc.alive else None),
            "turn": (time.monotonic() - state.started if state else None),
            "queued": self.queue.qsize(),
            "last": self.last_turn,
        }

    # ------------------------------------------------------------------ internals

    async def _stop_process_locked(self) -> None:
        if self.proc is not None:
            await self.proc.stop()
            self.proc = None

    def _arm_idle_timer(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_stop(), name=f"idle-{self.topic_id}")

    async def _idle_stop(self) -> None:
        await asyncio.sleep(settings.IDLE_TIMEOUT_SECS)
        if self.current is None and self.queue.empty():
            log.info("topic %s idle, stopping claude", self.topic_id)
            await self.stop_process()

    async def _loop(self) -> None:
        while True:
            request = await self.queue.get()
            try:
                await self._run_turn(request)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("topic %s: turn failed unexpectedly", self.topic_id)
                await self.app.sender.send_text(self.chat_id, self.thread_id, texts.TURN_INTERNAL_ERROR,
                                                topic_id=self.topic_id, role="verdict")
            finally:
                self.current = None
                self.queue.task_done()
                self._arm_idle_timer()

    async def _ensure_process(self, topic: dict) -> None:
        async with self._lock:
            if self.proc is not None and self.proc.alive:
                return
            self.proc = None
            proc = ClaudeProcess(build_argv(topic, resume=bool(topic["session_resumable"])), topic["cwd"], child_env())
            await proc.start()
            self.proc = proc

    async def _typing(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                await self.app.bot.send_chat_action(self.chat_id, "typing", message_thread_id=self.thread_id)
            except Exception as e:  # cosmetic
                log.debug("typing failed: %r", e)
            await asyncio.sleep(settings.TYPING_INTERVAL)

    async def _run_turn(self, request: TurnRequest) -> None:
        store = self.app.store
        if self._idle_task:
            self._idle_task.cancel()
        turn_id = request.turn_id or (await store.turns.create(self.topic_id, request.content))["id"]
        await store.turns.set_running(turn_id)
        state = TurnState(turn_id=turn_id, request=request)
        self.current = state
        typing = asyncio.create_task(self._typing(), name=f"typing-{turn_id}")
        try:
            for attempt in (1, 2):
                topic = await store.topics.get_by_id(self.topic_id)
                await self._ensure_process(topic)
                proc = self.proc
                await proc.send_user(request.content)
                await self._consume(proc, state, topic)
                if state.result is not None or state.cancelled or state.timed_out or state.aborted:
                    break
                # EOF without a result: the process died
                code = await proc.stop(grace=1)
                log.warning("topic %s: claude died (code %s) on attempt %s", self.topic_id, code, attempt)
                self.proc = None
                if attempt == 1:
                    if not state.got_init and topic["session_resumable"]:
                        # --resume failed before init: fall back to a fresh --session-id with the same uuid
                        await store.topics.update(self.topic_id, session_resumable=False)
                    continue
                await self._finish_crash(state, code, proc.stderr_tail)
                return
            await self._finish(state)
        finally:
            typing.cancel()

    async def _consume(self, proc: ClaudeProcess, state: TurnState, topic: dict) -> None:
        try:
            async with asyncio.timeout(settings.TURN_TIMEOUT_SECS):
                async for raw in proc.events():
                    await self._handle(raw, state, topic)
                    if state.result is not None:
                        return
        except TimeoutError:
            state.timed_out = True
            proc.interrupt()
            try:
                async with asyncio.timeout(5):
                    async for raw in proc.events():
                        await self._handle(raw, state, topic)
                        if state.result is not None:
                            return
            except TimeoutError:
                pass

    async def _handle(self, raw: dict, state: TurnState, topic: dict) -> None:
        for e in ev.parse_event(raw):
            if isinstance(e, ev.Init):
                state.got_init = True
                if e.session_id and str(e.session_id) != str(topic["session_id"]):
                    log.info("topic %s: session id changed %s -> %s", self.topic_id, topic["session_id"], e.session_id)
                    await self.app.store.topics.update(self.topic_id, session_id=uuid.UUID(e.session_id))
                    topic["session_id"] = e.session_id
            elif isinstance(e, ev.TextBlock):
                if e.parent_tool_use_id is None and e.text.strip():
                    state.texts_sent += 1
                    await self.app.sender.send_markdown(self.chat_id, self.thread_id, e.text,
                                                        topic_id=self.topic_id, turn_id=state.turn_id, role="assistant")
            elif isinstance(e, ev.PermissionDenied):
                state.denials.append(e.tool_name)
            elif isinstance(e, ev.CompactBoundary):
                state.compacted = True
                state.compact_pre_tokens = e.pre_tokens
            elif isinstance(e, ev.Result):
                state.result = e
                if e.session_id and str(e.session_id) != str(topic["session_id"]):
                    await self.app.store.topics.update(self.topic_id, session_id=uuid.UUID(e.session_id))
                    topic["session_id"] = e.session_id

    async def _finish(self, state: TurnState) -> None:
        store, sender = self.app.store, self.app.sender
        r = state.result
        send = lambda text: sender.send_text(self.chat_id, self.thread_id, text,  # noqa: E731
                                             topic_id=self.topic_id, turn_id=state.turn_id, role="verdict")
        if state.aborted:
            return
        if state.cancelled or state.timed_out:
            if state.got_init:  # the CLI wrote the transcript, so the session can be resumed
                await store.topics.update(self.topic_id, session_resumable=True)
            status = "cancelled" if state.cancelled else "timeout"
            await store.turns.finish(state.turn_id, status=status, result_subtype=r.subtype if r else None)
            await self._drop_dead_process()
            await send(texts.CANCELLED if state.cancelled else texts.TURN_TIMEOUT)
            return
        assert r is not None
        await store.topics.update(self.topic_id, session_resumable=True)
        status = "error" if r.is_error else "done"
        await store.turns.finish(state.turn_id, status=status, result_subtype=r.subtype, duration_ms=r.duration_ms,
                                 num_turns=r.num_turns, cost_usd=r.total_cost_usd, usage=r.usage,
                                 error=(r.result if r.is_error else None))
        self.last_turn = {"duration_ms": r.duration_ms, "cost_usd": r.total_cost_usd, "num_turns": r.num_turns,
                          "usage": r.usage}
        if r.subtype in ("error_max_turns", "error_max_budget_usd"):
            await send(texts.TURN_LIMIT.format(what="ходов" if "turns" in r.subtype else "бюджета"))
        elif r.is_error:
            await send(texts.TURN_ERROR.format(error=(r.result or r.subtype)[:1500]))
        elif state.compacted and state.texts_sent == 0:
            await send(texts.COMPACTED.format(pre_tokens=state.compact_pre_tokens or "?"))
        elif state.texts_sent == 0:
            await send(texts.TURN_NO_TEXT)
        if state.denials:
            await send(texts.DENIED.format(tools=", ".join(dict.fromkeys(state.denials))))
        if settings.SHOW_TURN_STATS:
            await send(texts.turn_stats(r.duration_ms, r.total_cost_usd, r.num_turns))

    async def _drop_dead_process(self) -> None:
        """After SIGINT the CLI exits on its own; make sure it is gone and forget it."""
        async with self._lock:
            if self.proc is not None:
                await self.proc.stop(grace=5)
                self.proc = None

    async def _finish_crash(self, state: TurnState, code: int | None, stderr_tail) -> None:
        await self.app.store.turns.finish(state.turn_id, status="crashed", error="\n".join(stderr_tail)[:2000])
        tail = "\n".join(stderr_tail).strip()
        await self.app.sender.send_text(self.chat_id, self.thread_id, texts.crash(code, tail),
                                        topic_id=self.topic_id, turn_id=state.turn_id, role="verdict")


class RuntimeRegistry:
    def __init__(self, app):
        self.app = app
        self._by_topic: dict[int, TopicRuntime] = {}

    def get(self, topic: dict) -> TopicRuntime:
        rt = self._by_topic.get(topic["id"])
        if rt is None:
            rt = TopicRuntime(self.app, topic)
            self._by_topic[topic["id"]] = rt
        return rt

    def peek(self, topic_id: int) -> TopicRuntime | None:
        return self._by_topic.get(topic_id)

    async def shutdown_all(self) -> None:
        for rt in list(self._by_topic.values()):
            try:
                await rt.shutdown()
            except Exception:
                log.exception("shutdown of topic %s failed", rt.topic_id)
        self._by_topic.clear()
