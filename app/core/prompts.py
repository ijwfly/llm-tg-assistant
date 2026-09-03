"""Prompt tool requests from Claude Code turned into Telegram cards and back into decisions
(PROJECT_SPEC 4.6-4.7). One `PendingPrompt` per request; buttons and awaited text resolve it."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import settings
from app.bridge.rules import Rule, always_rule, permission_update
from app.render import cards, keyboards
from app.transport import texts

log = logging.getLogger(__name__)

PERMISSION, QUESTION, PLAN = "permission", "question", "plan"


def deny(message: str) -> dict:
    return {"behavior": "deny", "message": message}


@dataclass
class PendingPrompt:
    id: int
    topic: dict
    turn_id: int | None
    kind: str
    tool_name: str
    tool_input: dict
    tool_use_id: str | None
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    card_row: int | None = None          # outbox row of the current card
    message_id: int | None = None        # learned from the callback or the outbox
    card_text: str = ""                  # markdown of the current card (the verdict is appended to it)
    rule: Rule | None = None
    awaiting_text: bool = False
    q_index: int = 0
    answers: dict = field(default_factory=dict)
    selected: set = field(default_factory=set)

    @property
    def questions(self) -> list[dict]:
        return list(self.tool_input.get("questions") or [])

    @property
    def question(self) -> dict:
        qs = self.questions
        return qs[self.q_index] if self.q_index < len(qs) else {}

    @property
    def open(self) -> bool:
        return not self.future.done()


class PromptService:
    def __init__(self, app):
        self.app = app
        self._by_token: dict[str, object] = {}
        self._pending: dict[int, PendingPrompt] = {}

    # ---------------------------------------------------------------- runtimes

    def register(self, token: str, runtime) -> None:
        self._by_token[token] = runtime

    def unregister(self, token: str | None) -> None:
        if token:
            self._by_token.pop(token, None)

    def pending_for(self, topic_id: int) -> list[PendingPrompt]:
        return [p for p in self._pending.values() if p.topic["id"] == topic_id and p.open]

    # ---------------------------------------------------------------- entry from the socket

    async def handle(self, request: dict, closed: asyncio.StreamReader | None = None) -> dict:
        rt = self._by_token.get(str(request.get("token") or ""))
        if rt is None or rt.current is None:
            return deny(texts.DENY_MSG_NO_TURN)
        args = request.get("args") or {}
        tool_name = str(args.get("tool_name") or "?")
        tool_input = args.get("input") if isinstance(args.get("input"), dict) else {}
        kind = QUESTION if tool_name == "AskUserQuestion" else PLAN if tool_name == "ExitPlanMode" else PERMISSION
        topic = await self.app.store.topics.get_by_id(rt.topic_id)
        state = rt.current
        prompt_id = await self.app.store.prompts.create(topic["id"], state.turn_id, kind, tool_name,
                                                        args.get("tool_use_id"), tool_input)
        p = PendingPrompt(prompt_id, topic, state.turn_id, kind, tool_name, tool_input, args.get("tool_use_id"))
        self._pending[p.id] = p
        timeout = settings.PERMISSION_TIMEOUT_SECS if kind == PERMISSION else settings.QUESTION_TIMEOUT_SECS
        watch = asyncio.create_task(closed.read()) if closed is not None else None
        try:
            await self._send_card(p)
            self._set_waiting(rt, p)
            waiters = {p.future} | ({watch} if watch else set())
            done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if p.future in done:
                return p.future.result()
            if watch in done:   # the MCP client went away (claude died or was interrupted)
                await self.resolve(p, deny(texts.DENY_MSG_CANCELLED), texts.PERM_CANCELLED, status="cancelled")
                return p.future.result()
            minutes = int(timeout // 60) or 1
            await self.resolve(p, deny(texts.DENY_MSG_TIMEOUT.format(minutes=minutes)), texts.PERM_TIMEOUT,
                               status="timeout")
            return p.future.result()
        finally:
            if watch:
                watch.cancel()
            self._pending.pop(p.id, None)
            if rt.current is state:
                state.progress.waiting = None
                if state.live:
                    state.live.touch()

    def _set_waiting(self, rt, p: PendingPrompt) -> None:
        state = rt.current
        if state is None:
            return
        state.progress.waiting = (texts.WAITING_PERMISSION.format(tool=p.tool_name) if p.kind == PERMISSION
                                  else texts.WAITING_QUESTION if p.kind == QUESTION else texts.WAITING_PLAN)
        if state.live:
            state.live.touch()

    # ---------------------------------------------------------------- cards

    async def _send_card(self, p: PendingPrompt) -> None:
        topic = p.topic
        if p.kind == PERMISSION:
            p.rule = always_rule(p.tool_name, p.tool_input)
            p.card_text = cards.permission_card(p.tool_name, p.tool_input, topic["cwd"])
            kb = keyboards.permission_kb(topic["id"], p.id, p.rule.text if p.rule else None)
        elif p.kind == QUESTION:
            q = p.question
            p.selected = set()
            p.card_text = cards.question_card(q, p.q_index, len(p.questions))
            kb = keyboards.question_kb(topic["id"], p.id, [cards.option_label(o) for o in q.get("options") or []],
                                       multi=bool(q.get("multiSelect")))
        else:
            p.card_text = cards.plan_card(str(p.tool_input.get("plan") or ""))
            kb = keyboards.plan_kb(topic["id"], p.id)
        rows = await self.app.sender.send_markdown(topic["chat_id"], topic["thread_id"], p.card_text, reply_markup=kb,
                                                   topic_id=topic["id"], turn_id=p.turn_id, role="prompt")
        p.card_row = rows[-1]
        p.message_id = None

    async def _card_message_id(self, p: PendingPrompt) -> int | None:
        if p.message_id:
            return p.message_id
        if p.card_row is None:
            return None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            row = await self.app.store.outbox.get(p.card_row)
            if row and row["status"] != "pending":
                return row["delivered_message_id"]
            await asyncio.sleep(0.05)
        return None

    async def _edit_card(self, p: PendingPrompt, tail: str, kb=None) -> None:
        mid = await self._card_message_id(p)
        if mid is None:
            return
        topic = p.topic
        text = p.card_text if kb is not None else f"{p.card_text}\n\n{tail}"
        await self.app.sender.edit_markdown(topic["chat_id"], topic["thread_id"], mid, text, reply_markup=kb,
                                            topic_id=topic["id"])

    async def resolve(self, p: PendingPrompt, decision: dict, verdict: str, *, status: str = "answered") -> None:
        if not p.open:
            return
        p.future.set_result(decision)
        p.awaiting_text = False
        await self.app.store.prompts.resolve(p.id, status, decision)
        await self._edit_card(p, verdict)

    async def abandon(self, topic_id: int, message: str, verdict: str) -> None:
        for p in self.pending_for(topic_id):
            await self.resolve(p, deny(message), verdict, status="cancelled")

    # ---------------------------------------------------------------- buttons

    def _get(self, prompt_id: int, message_id: int | None) -> PendingPrompt | None:
        p = self._pending.get(prompt_id)
        if p is None or not p.open:
            return None
        if message_id:
            p.message_id = message_id
        return p

    async def permission(self, prompt_id: int, choice: str, message_id: int | None = None) -> str:
        p = self._get(prompt_id, message_id)
        if p is None or p.kind != PERMISSION:
            return texts.TOAST_PROMPT_STALE
        if choice == "allow":
            await self.resolve(p, {"behavior": "allow", "updatedInput": p.tool_input}, texts.PERM_ALLOWED)
            return texts.TOAST_ALLOWED
        if choice == "deny":
            await self.resolve(p, deny(texts.DENY_MSG_USER), texts.PERM_DENIED)
            return texts.TOAST_DENIED
        if choice == "always" and p.rule is not None:
            await self.app.store.rules.add(p.topic["id"], p.rule.text)
            await self.resolve(p, {"behavior": "allow", "updatedInput": p.tool_input,
                                   "updatedPermissions": [permission_update(p.rule)]},
                               texts.PERM_ALWAYS.format(rule=p.rule.text))
            return texts.TOAST_ALWAYS
        if choice == "comment":
            return await self._await_text(p, texts.PERM_ASK_COMMENT)
        return texts.TOAST_PROMPT_STALE

    async def _await_text(self, p: PendingPrompt, hint: str) -> str:
        for other in self.pending_for(p.topic["id"]):
            other.awaiting_text = False
        p.awaiting_text = True
        await self.app.sender.send_text(p.topic["chat_id"], p.topic["thread_id"], hint, topic_id=p.topic["id"])
        return texts.TOAST_WRITE_NEXT

    async def question_option(self, prompt_id: int, index: int, message_id: int | None = None) -> str:
        p = self._get(prompt_id, message_id)
        if p is None or p.kind != QUESTION:
            return texts.TOAST_PROMPT_STALE
        q = p.question
        options = q.get("options") or []
        if index < 0 or index >= len(options):
            return texts.TOAST_PROMPT_STALE
        if q.get("multiSelect"):
            p.selected ^= {index}
            kb = keyboards.question_kb(p.topic["id"], p.id, [cards.option_label(o) for o in options], multi=True,
                                       selected=p.selected)
            await self._edit_card(p, "", kb)
            return texts.TOAST_CHOSEN
        await self._answer_question(p, str(options[index].get("label") or ""))
        return texts.TOAST_CHOSEN

    async def question_done(self, prompt_id: int, message_id: int | None = None) -> str:
        p = self._get(prompt_id, message_id)
        if p is None or p.kind != QUESTION:
            return texts.TOAST_PROMPT_STALE
        options = p.question.get("options") or []
        labels = [str(options[i].get("label") or "") for i in sorted(p.selected) if i < len(options)]
        await self._answer_question(p, labels)
        return texts.TOAST_CHOSEN

    async def question_custom(self, prompt_id: int, message_id: int | None = None) -> str:
        p = self._get(prompt_id, message_id)
        if p is None or p.kind != QUESTION:
            return texts.TOAST_PROMPT_STALE
        return await self._await_text(p, texts.QUESTION_ASK_CUSTOM)

    async def _answer_question(self, p: PendingPrompt, answer) -> None:
        p.awaiting_text = False
        p.answers[str(p.question.get("question") or p.q_index)] = answer
        shown = ", ".join(answer) if isinstance(answer, list) else str(answer)
        await self._edit_card(p, texts.QUESTION_ANSWERED.format(answer=shown))
        p.q_index += 1
        if p.q_index < len(p.questions):
            await self._send_card(p)
            return
        decision = {"behavior": "allow", "updatedInput": {**p.tool_input, "answers": p.answers}}
        p.future.set_result(decision)
        await self.app.store.prompts.resolve(p.id, "answered", decision)

    async def plan(self, prompt_id: int, choice: str, message_id: int | None = None) -> str:
        p = self._get(prompt_id, message_id)
        if p is None or p.kind != PLAN:
            return texts.TOAST_PROMPT_STALE
        if choice in ("accept", "ask"):
            mode, bridge_mode = ("acceptEdits", "acceptEdits") if choice == "accept" else ("default", "prompt")
            await self.app.store.topics.update(p.topic["id"], permission_mode=bridge_mode)
            await self.resolve(p, {"behavior": "allow", "updatedInput": p.tool_input,
                                   "updatedPermissions": [{"type": "setMode", "mode": mode, "destination": "session"}]},
                               texts.PLAN_ACCEPTED if choice == "accept" else texts.PLAN_ACCEPTED_ASK)
            return texts.TOAST_ALLOWED
        if choice == "rework":
            return await self._await_text(p, texts.PLAN_REWORK)
        return texts.TOAST_PROMPT_STALE

    # ---------------------------------------------------------------- awaited text

    async def consume_text(self, topic: dict, text: str) -> bool:
        """The next text message of a topic answers a card that asked for it. True if consumed."""
        p = next((p for p in self.pending_for(topic["id"]) if p.awaiting_text), None)
        if p is None:
            return False
        text = text.strip()
        if not text:
            return False
        if p.kind == PERMISSION:
            await self.resolve(p, deny(texts.DENY_MSG_COMMENT.format(text=text)), texts.PERM_DENIED_WITH.format(text=text[:300]))
        elif p.kind == PLAN:
            await self.resolve(p, deny(texts.DENY_MSG_PLAN_REWORK.format(text=text)), texts.PLAN_REWORKED.format(text=text[:300]))
        else:
            await self._answer_question(p, text)
        return True
