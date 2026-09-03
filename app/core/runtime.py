"""Per-topic runtime: the claude process, the turn queue, the turn loop and the live view."""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import settings
from app.bridge import events as ev
from app.bridge.cli import build_argv, child_env
from app.bridge.process import ClaudeProcess
from app.core import prefs
from app.core.liveview import LiveView
from app.core.voice import voice_for_turn
from app.render import keyboards
from app.render.markdown import RICH_LIMIT
from app.render.progress import ProgressState, draft_markdown, progress_text
from app.transport import texts

log = logging.getLogger(__name__)


@dataclass
class TurnRequest:
    content: list[dict]                 # content blocks for the user message
    turn_id: int | None = None          # set when re-running an existing turn row (/retry creates a new one)
    quiet: bool = False                 # housekeeping turn (/rename): no "no text" verdict


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
    pending: str = ""                   # finalized text not yet sent (short segments are merged)
    stream_buf: str = ""                # text deltas of the block being generated
    progress: ProgressState = field(default_factory=lambda: ProgressState(started=time.monotonic()))
    live: LiveView | None = None
    topic: dict = field(default_factory=dict)
    model: str | None = None            # from system/init
    spoken: list[str] = field(default_factory=list)   # text segments sent, for the voice answer

    @property
    def preview_text(self) -> str:
        return self.pending + ("\n\n" if self.pending and self.stream_buf else "") + self.stream_buf


class QueueFull(Exception):
    pass


class TopicRuntime:
    def __init__(self, app, topic: dict):
        self.app = app
        self.topic_id: int = topic["id"]
        self.chat_id: int = topic["chat_id"]
        self.thread_id: int | None = topic["thread_id"]
        self.private: bool = topic["chat_id"] > 0
        self.key = f"{self.chat_id}:{self.thread_id or 0}"
        self.queue: asyncio.Queue[TurnRequest] = asyncio.Queue(maxsize=settings.TURN_QUEUE_MAX)
        self.proc: ClaudeProcess | None = None
        self.prompt_token: str | None = None   # identifies this process to the bridge MCP server
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
        await self.app.prompts.abandon(self.topic_id, texts.DENY_MSG_CANCELLED, texts.PERM_CANCELLED)
        return True

    async def stop_process(self) -> None:
        async with self._lock:
            await self._stop_process_locked()

    async def restart_context(self, *, cwd: str | None = None) -> dict:
        """New session id (and optionally a new directory). The old transcript stays on disk."""
        async with self._lock:
            await self._stop_process_locked()
            await self.app.store.topics.remember_past_session(self.topic_id)
            fields = {"session_id": uuid.uuid4(), "session_resumable": False}
            if cwd:
                fields["cwd"] = cwd
            return await self.app.store.topics.update(self.topic_id, **fields)

    async def shutdown(self) -> None:
        state = self.current
        if state is not None:
            state.aborted = True
            await self.app.store.turns.finish(state.turn_id, status="aborted")
            if state.live:
                await state.live.finish()
            await self.app.sender.send_text(self.chat_id, self.thread_id, texts.DAEMON_STOPPED,
                                            reply_markup=keyboards.retry_kb(self.topic_id),
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
            "waiting": (state.progress.waiting if state else None),
        }

    # ------------------------------------------------------------------ internals

    async def _stop_process_locked(self) -> None:
        if self.proc is not None:
            await self.proc.stop()
            self.proc = None
        self.app.prompts.unregister(self.prompt_token)
        self.prompt_token = None

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
                if self.current and self.current.live:
                    await self.current.live.finish()
                await self.app.sender.send_text(self.chat_id, self.thread_id, texts.TURN_INTERNAL_ERROR,
                                                reply_markup=keyboards.retry_kb(self.topic_id),
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
            self.app.prompts.unregister(self.prompt_token)
            self.prompt_token = secrets.token_urlsafe(12)
            self.app.prompts.register(self.prompt_token, self)
            proc = ClaudeProcess(build_argv(topic, resume=bool(topic["session_resumable"]), prompt_token=self.prompt_token),
                                 topic["cwd"], child_env())
            await proc.start()
            self.proc = proc

    async def _typing(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if not (self.current and self.current.progress.waiting):   # no typing while a card waits for the user
                try:
                    await self.app.bot.send_chat_action(self.chat_id, "typing", message_thread_id=self.thread_id)
                except Exception as e:  # cosmetic
                    log.debug("typing failed: %r", e)
            await asyncio.sleep(settings.TYPING_INTERVAL)

    def _make_live(self, state: TurnState) -> LiveView:
        def render_draft() -> str:
            return draft_markdown(state.progress.line(time.monotonic()), state.progress.last_thinking_line(),
                                  state.preview_text, show_thinking=prefs.topic_flag(state.topic, "thinking_preview"),
                                  frozen_limit=RICH_LIMIT, streaming=bool(state.stream_buf))

        def render_message() -> str:
            return progress_text(state.progress.line(time.monotonic()), state.preview_text,
                                 preview_chars=settings.PREVIEW_TAIL,
                                 show_preview=prefs.topic_flag(state.topic, "stream_preview"))

        return LiveView(self.app, chat_id=self.chat_id, thread_id=self.thread_id, topic_id=self.topic_id,
                        turn_id=state.turn_id, private=self.private,
                        render_draft=render_draft, render_message=render_message)

    async def _run_turn(self, request: TurnRequest) -> None:
        store = self.app.store
        if self._idle_task:
            self._idle_task.cancel()
        turn_id = request.turn_id or (await store.turns.create(self.topic_id, request.content))["id"]
        await store.turns.set_running(turn_id)
        state = TurnState(turn_id=turn_id, request=request, topic=await store.topics.get_by_id(self.topic_id) or {})
        state.live = self._make_live(state)
        self.current = state
        typing = asyncio.create_task(self._typing(), name=f"typing-{turn_id}")
        state.live.start()
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
            await self.app.prompts.abandon(self.topic_id, texts.DENY_MSG_CANCELLED, texts.PERM_CANCELLED)
            if state.live:
                await state.live.finish()

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
                state.model = e.model
                if e.session_id and str(e.session_id) != str(topic["session_id"]):
                    log.info("topic %s: session id changed %s -> %s", self.topic_id, topic["session_id"], e.session_id)
                    await self.app.store.topics.update(self.topic_id, session_id=uuid.UUID(e.session_id))
                    topic["session_id"] = e.session_id
                if (topic.get("settings") or {}).get("fork"):   # the fork happened: never fork again
                    topic = await self.app.store.topics.update_settings(self.topic_id, fork=None)
            elif isinstance(e, ev.TextDelta):
                state.stream_buf += e.text
                state.live.touch()
            elif isinstance(e, ev.ThinkingDelta):
                state.progress.add_thinking(e.text)
                state.live.touch()
            elif isinstance(e, ev.TextBlock):
                state.stream_buf = ""
                if e.parent_tool_use_id is None and e.text.strip():
                    state.pending = (state.pending + "\n\n" + e.text) if state.pending else e.text
                    if len(state.pending) >= settings.MIN_SEGMENT_CHARS:
                        await self._flush_text(state)
                    else:
                        state.live.touch()
            elif isinstance(e, ev.ToolUse):
                state.progress.add_tool(e.name, e.input, subagent=e.parent_tool_use_id is not None)
                state.live.touch()
            elif isinstance(e, ev.PermissionDenied):
                state.denials.append(e.tool_name)
            elif isinstance(e, ev.RateLimit):
                self.app.runtimes.rate_limit = e.info
            elif isinstance(e, ev.CompactBoundary):
                state.compacted = True
                state.compact_pre_tokens = e.pre_tokens
            elif isinstance(e, ev.Result):
                state.result = e
                if e.session_id and str(e.session_id) != str(topic["session_id"]):
                    await self.app.store.topics.update(self.topic_id, session_id=uuid.UUID(e.session_id))
                    topic["session_id"] = e.session_id

    async def _flush_text(self, state: TurnState) -> None:
        text, state.pending = state.pending, ""
        if not text.strip():
            return
        state.texts_sent += 1
        state.spoken.append(text)
        sender = self.app.sender
        if len(text) > settings.ANSWER_FILE_THRESHOLD:
            out_dir = Path(settings.INBOX_DIR) / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"answer-{state.turn_id}.md"
            path.write_text(text)
            await sender.send_markdown(self.chat_id, self.thread_id, text[:2000] + "\n\n…",
                                       topic_id=self.topic_id, turn_id=state.turn_id, role="assistant")
            await sender.send_document(self.chat_id, self.thread_id, str(path), caption=texts.ANSWER_IN_FILE,
                                       topic_id=self.topic_id, turn_id=state.turn_id, role="assistant")
            return
        await sender.send_markdown(self.chat_id, self.thread_id, text,
                                   topic_id=self.topic_id, turn_id=state.turn_id, role="assistant")

    async def _finish(self, state: TurnState) -> None:
        store, sender = self.app.store, self.app.sender
        r = state.result
        tid = self.topic_id

        async def send(text: str, kb=None) -> None:
            await sender.send_text(self.chat_id, self.thread_id, text, reply_markup=kb,
                                   topic_id=tid, turn_id=state.turn_id, role="verdict")

        if state.aborted:
            return
        if state.cancelled or state.timed_out:
            if state.pending.strip():
                state.pending += "\n\n_(прервано)_"
                await self._flush_text(state)
            if state.got_init:  # the CLI wrote the transcript, so the session can be resumed
                await store.topics.update(tid, session_resumable=True)
            status = "cancelled" if state.cancelled else "timeout"
            await store.turns.finish(state.turn_id, status=status, result_subtype=r.subtype if r else None)
            await self._drop_dead_process()
            await send(texts.CANCELLED if state.cancelled else texts.TURN_TIMEOUT, keyboards.retry_kb(tid))
            return
        assert r is not None
        await self._flush_text(state)
        await store.topics.update(tid, session_resumable=True)
        status = "error" if r.is_error else "done"
        await store.turns.finish(state.turn_id, status=status, result_subtype=r.subtype, duration_ms=r.duration_ms,
                                 num_turns=r.num_turns, cost_usd=r.total_cost_usd, usage=r.usage,
                                 error=(r.result if r.is_error else None), model=state.model)
        self.last_turn = {"duration_ms": r.duration_ms, "cost_usd": r.total_cost_usd, "num_turns": r.num_turns,
                          "usage": r.usage}
        if r.subtype in ("error_max_turns", "error_max_budget_usd"):
            await send(texts.TURN_LIMIT.format(what="ходов" if "turns" in r.subtype else "бюджета"),
                       keyboards.continue_kb(tid))
        elif r.is_error:
            await send(texts.TURN_ERROR.format(error=(r.result or r.subtype)[:1500]), keyboards.retry_kb(tid))
        elif state.compacted and state.texts_sent == 0:
            await send(texts.COMPACTED.format(pre_tokens=state.compact_pre_tokens or "?"))
        elif state.texts_sent == 0 and not state.request.quiet:
            await send(texts.TURN_NO_TEXT)
        if not r.is_error:
            await self._rename_implicit_topic(state)
        if state.denials:
            await send(texts.DENIED.format(tools=", ".join(dict.fromkeys(state.denials))), keyboards.denied_kb(tid))
        if prefs.topic_flag(state.topic, "show_turn_stats"):
            await send(texts.turn_stats(r.duration_ms, r.total_cost_usd, r.num_turns))
        if prefs.topic_flag(state.topic, "voice") and state.spoken and settings.TTS_CMD:
            path = await voice_for_turn(state.spoken, state.turn_id)
            if path:
                await sender.send_voice(self.chat_id, self.thread_id, str(path), topic_id=tid, turn_id=state.turn_id)

    async def _rename_implicit_topic(self, state: TurnState) -> None:
        """A topic the user created without a name gets one from the first prompt (PROJECT_SPEC 4.2)."""
        topic = await self.app.store.topics.get_by_id(self.topic_id)
        if not topic or not (topic.get("settings") or {}).get("title_implicit") or not self.thread_id:
            return
        text = " ".join(b.get("text", "") for b in state.request.content if b.get("type") == "text")
        title = " ".join(text.split())[:40].strip()
        if not title or title.startswith("/"):
            return
        from app.core import actions
        await actions.rename_topic(self.app, topic, title, tell_claude=False)

    async def _drop_dead_process(self) -> None:
        """After SIGINT the CLI exits on its own; make sure it is gone and forget it."""
        async with self._lock:
            if self.proc is not None:
                await self.proc.stop(grace=5)
                self.proc = None
            self.app.prompts.unregister(self.prompt_token)
            self.prompt_token = None

    async def _finish_crash(self, state: TurnState, code: int | None, stderr_tail) -> None:
        await self.app.store.turns.finish(state.turn_id, status="crashed", error="\n".join(stderr_tail)[:2000])
        tail = "\n".join(stderr_tail).strip()
        await self.app.sender.send_text(self.chat_id, self.thread_id, texts.crash(code, tail),
                                        reply_markup=keyboards.retry_kb(self.topic_id),
                                        topic_id=self.topic_id, turn_id=state.turn_id, role="verdict")


class RuntimeRegistry:
    def __init__(self, app):
        self.app = app
        self._by_topic: dict[int, TopicRuntime] = {}
        self.rate_limit: dict | None = None   # last rate_limit_event of any topic (subscription windows)

    def get(self, topic: dict) -> TopicRuntime:
        rt = self._by_topic.get(topic["id"])
        if rt is None:
            rt = TopicRuntime(self.app, topic)
            self._by_topic[topic["id"]] = rt
        return rt

    def peek(self, topic_id: int) -> TopicRuntime | None:
        return self._by_topic.get(topic_id)

    async def drop(self, topic_id: int) -> None:
        rt = self._by_topic.pop(topic_id, None)
        if rt is not None:
            await rt.shutdown()

    async def shutdown_all(self) -> None:
        for rt in list(self._by_topic.values()):
            try:
                await rt.shutdown()
            except Exception:
                log.exception("shutdown of topic %s failed", rt.topic_id)
        self._by_topic.clear()
