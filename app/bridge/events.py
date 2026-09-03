"""Typed view over stream-json events (shapes verified in specs/PHASE_0_SPIKE.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Init:
    session_id: str
    model: str | None
    permission_mode: str | None
    raw: dict


@dataclass
class TextBlock:
    text: str
    parent_tool_use_id: str | None


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict
    parent_tool_use_id: str | None


@dataclass
class ToolResult:
    tool_use_id: str
    content: Any
    is_error: bool
    parent_tool_use_id: str | None


@dataclass
class Thinking:
    text: str


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolUseStart:
    name: str


@dataclass
class PermissionDenied:
    tool_name: str
    tool_use_id: str | None
    reason: str | None


@dataclass
class CompactBoundary:
    pre_tokens: int | None
    trigger: str | None


@dataclass
class ApiRetry:
    attempt: int
    max_retries: int
    error: str | None


@dataclass
class RateLimit:
    info: dict


@dataclass
class UserEcho:
    """A replayed user message (with --replay-user-messages) or an injected one."""
    text: str | None
    uuid: str | None


@dataclass
class Result:
    subtype: str
    is_error: bool
    session_id: str | None
    result: str | None
    duration_ms: int | None
    num_turns: int | None
    total_cost_usd: float | None
    usage: dict | None
    permission_denials: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Other:
    type: str
    subtype: str | None
    raw: dict


Event = (Init | TextBlock | ToolUse | ToolResult | Thinking | TextDelta | ThinkingDelta | ToolUseStart
         | PermissionDenied | CompactBoundary | ApiRetry | RateLimit | UserEcho | Result | Other)


def _content_blocks(ev: dict) -> list:
    content = (ev.get("message") or {}).get("content") or []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def parse_event(ev: dict) -> list[Event]:
    """One stdout line may carry several blocks; returns them in order."""
    t = ev.get("type")
    if t == "system":
        st = ev.get("subtype")
        if st == "init":
            return [Init(ev.get("session_id"), ev.get("model"), ev.get("permissionMode"), ev)]
        if st == "permission_denied":
            return [PermissionDenied(ev.get("tool_name", "?"), ev.get("tool_use_id"), ev.get("decision_reason"))]
        if st == "compact_boundary":
            meta = ev.get("compact_metadata") or {}
            return [CompactBoundary(meta.get("pre_tokens"), meta.get("trigger"))]
        if st == "api_retry":
            return [ApiRetry(ev.get("attempt", 0), ev.get("max_retries", 0), ev.get("error"))]
        return [Other(t, st, ev)]
    if t == "assistant":
        out: list[Event] = []
        parent = ev.get("parent_tool_use_id")
        for b in _content_blocks(ev):
            bt = b.get("type")
            if bt == "text":
                out.append(TextBlock(b.get("text", ""), parent))
            elif bt == "tool_use":
                out.append(ToolUse(b.get("id", ""), b.get("name", "?"), b.get("input") or {}, parent))
            elif bt == "thinking":
                out.append(Thinking(b.get("thinking", "")))
        return out or [Other(t, None, ev)]
    if t == "user":
        out = []
        parent = ev.get("parent_tool_use_id")
        for b in _content_blocks(ev):
            if b.get("type") == "tool_result":
                out.append(ToolResult(b.get("tool_use_id", ""), b.get("content"), bool(b.get("is_error")), parent))
            elif b.get("type") == "text":
                out.append(UserEcho(b.get("text"), ev.get("uuid")))
        return out or [UserEcho(None, ev.get("uuid"))]
    if t == "stream_event":
        e = ev.get("event") or {}
        et = e.get("type")
        if et == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta":
                return [TextDelta(d.get("text", ""))]
            if d.get("type") == "thinking_delta":
                return [ThinkingDelta(d.get("thinking", ""))]
        elif et == "content_block_start":
            cb = e.get("content_block") or {}
            if cb.get("type") == "tool_use":
                return [ToolUseStart(cb.get("name", "?"))]
        return [Other(t, et, ev)]
    if t == "result":
        return [Result(
            subtype=ev.get("subtype", "unknown"), is_error=bool(ev.get("is_error")),
            session_id=ev.get("session_id"), result=ev.get("result"),
            duration_ms=ev.get("duration_ms"), num_turns=ev.get("num_turns"),
            total_cost_usd=ev.get("total_cost_usd"), usage=ev.get("usage"),
            permission_denials=ev.get("permission_denials") or [], raw=ev)]
    if t == "rate_limit_event":
        return [RateLimit(ev.get("rate_limit_info") or {})]
    return [Other(t or "?", ev.get("subtype"), ev)]
