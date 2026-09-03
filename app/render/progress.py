"""Progress line, tool trail and live-view content (draft / progress message)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.render.markdown import format_clock, preview_tail

PHRASES = [
    (20, ["уже смотрю 👀", "поехали 🚀", "секунду, гляну 🔍"]),
    (120, ["копаю ⛏️", "вникаю 🤔", "разбираюсь 🧩"]),
    (10 ** 9, ["завари чай, я ещё вожусь 🍵", "это надолго, но я тут 🐢", "работаю, не переключайся 🛠️"]),
]
DETAIL_LIMIT = 60
TRAIL_LEN = 3


def phrase_bucket(elapsed: float) -> int:
    for i, (limit, _) in enumerate(PHRASES):
        if elapsed < limit:
            return i
    return len(PHRASES) - 1


def pick_phrase(bucket: int, rnd: random.Random | None = None) -> str:
    return (rnd or random).choice(PHRASES[bucket][1])


def _cut_front(s: str, limit: int) -> str:
    return s if len(s) <= limit else "…" + s[-(limit - 1):]


def _cut_back(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def tool_detail(name: str, tool_input: dict) -> str | None:
    """One safe detail per tool; None for tools whose input may hold secrets (MCP and unknown)."""
    if name in ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        v = tool_input.get("file_path") or tool_input.get("notebook_path")
        return _cut_front(str(v), DETAIL_LIMIT) if v else None
    if name == "Bash":
        v = (tool_input.get("command") or "").split("\n", 1)[0]
        return _cut_back(v, DETAIL_LIMIT) if v else None
    if name in ("Grep", "Glob"):
        v = tool_input.get("pattern")
        return _cut_back(str(v), DETAIL_LIMIT) if v else None
    if name in ("Task", "Agent"):
        v = tool_input.get("description")
        return _cut_back(str(v), DETAIL_LIMIT) if v else None
    if name == "WebFetch":
        v = tool_input.get("url")
        return _cut_back(str(v), DETAIL_LIMIT) if v else None
    if name == "WebSearch":
        v = tool_input.get("query")
        return _cut_back(str(v), DETAIL_LIMIT) if v else None
    return None


@dataclass
class ProgressState:
    started: float
    trail: list[str] = field(default_factory=list)     # last tool names (with "Task ▸ " prefix for subagents)
    current_detail: str | None = None
    tool_count: int = 0
    bucket: int = -1
    phrase: str = ""
    thinking_tail: str = ""
    waiting: str | None = None                          # e.g. "🔐 жду разрешения (Bash)"

    def add_tool(self, name: str, tool_input: dict, subagent: bool) -> None:
        label = f"Task ▸ {name}" if subagent else name
        self.trail = (self.trail + [label])[-TRAIL_LEN:]
        self.current_detail = tool_detail(name, tool_input)
        self.tool_count += 1

    def add_thinking(self, delta: str) -> None:
        self.thinking_tail = (self.thinking_tail + delta)[-600:]

    def last_thinking_line(self, limit: int = 300) -> str:
        lines = [l.strip() for l in self.thinking_tail.splitlines() if l.strip()]
        if not lines:
            return ""
        line = lines[-1]
        return line if len(line) >= 10 else "Думаю…"
        # short fragments read badly; the spec asks for a placeholder

    def line(self, now: float, rnd: random.Random | None = None) -> str:
        elapsed = now - self.started
        bucket = phrase_bucket(elapsed)
        if bucket != self.bucket:
            self.bucket = bucket
            self.phrase = pick_phrase(bucket, rnd)
        if self.waiting:
            return f"{self.waiting} ({self.tool_count} · {format_clock(elapsed)})"
        trail = " → ".join(self.trail)
        if trail and self.current_detail:
            trail = f"{trail} {self.current_detail}"
        parts = [self.phrase]
        if trail:
            parts.append(trail)
        return f"{' '.join(parts)} ({self.tool_count} · {format_clock(elapsed)})"


def draft_markdown(progress_line: str, thinking_line: str, text: str, *, show_thinking: bool,
                   frozen_limit: int, streaming: bool = False) -> str:
    """`streaming=True` means the last text block is still being generated: apply the preview rules
    (nothing under 50 chars, hold back the unfinished last word)."""
    head = progress_line
    if show_thinking and thinking_line:
        head += f"\n🧠 {thinking_line[:300]}"
    body = preview_tail(text, frozen_limit) if streaming else text
    if len(body) > frozen_limit:
        body = body[:frozen_limit] + " ⏳…"
    md = f"<tg-thinking>{head}</tg-thinking>"
    if body:
        md += "\n" + body
    return md


def progress_text(progress_line: str, text: str, *, preview_chars: int, show_preview: bool) -> str:
    tail = preview_tail(text, preview_chars) if show_preview else ""
    return f"{progress_line}\n—\n{tail}" if tail else progress_line
