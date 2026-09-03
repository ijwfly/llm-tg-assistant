"""Text splitting and preview rules for Telegram limits (fence-aware)."""
from __future__ import annotations

import re

RICH_LIMIT = 30_000
PLAIN_LIMIT = 4_000
PREVIEW_MIN_CHARS = 50

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+#.-]*)")


def split_text(text: str, limit: int) -> list[str]:
    """Split by newlines, never exceeding `limit`; a single overlong line is hard-cut."""
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        piece = line if not current else "\n" + line
        if len(current) + len(piece) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def _open_fence_at(lines: list[str]) -> tuple[str, str] | None:
    """If the lines end inside a code fence, return (fence, language)."""
    open_fence = None
    for line in lines:
        m = _FENCE_RE.match(line)
        if not m:
            continue
        if open_fence is None:
            open_fence = (m.group(1), m.group(2))
        elif m.group(1)[0] == open_fence[0][0] and len(m.group(1)) >= len(open_fence[0]):
            open_fence = None
    return open_fence


def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def split_markdown(text: str, limit: int = RICH_LIMIT) -> list[str]:
    """Split markdown into chunks <= limit: prefer paragraph, line, sentence, space boundaries;
    close an open code fence at the end of a chunk and reopen it (same language) in the next;
    never cut a table block in the middle."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        for sep in ("\n\n", "\n", ". ", " "):
            idx = window.rfind(sep)
            if idx > limit // 4:
                cut = idx + (len(sep) if sep in (". ", " ") else 0)
                break
        if cut <= 0:
            cut = limit
        head, tail = rest[:cut], rest[cut:]
        # don't split inside a table: move the cut to the start of the table block
        head_lines = head.split("\n")
        if head_lines and _is_table_line(head_lines[-1]) and tail.lstrip("\n").split("\n", 1)[0].strip().startswith("|"):
            i = len(head_lines) - 1
            while i > 0 and _is_table_line(head_lines[i - 1]):
                i -= 1
            if i > 0:
                head = "\n".join(head_lines[:i])
                tail = "\n".join(head_lines[i:]) + ("\n" if not tail.startswith("\n") else "") + tail
        fence = _open_fence_at(head.split("\n"))
        if fence:
            head = head.rstrip("\n") + "\n" + fence[0]
            tail = f"{fence[0]}{fence[1]}\n" + tail.lstrip("\n")
        chunks.append(head.rstrip("\n"))
        rest = tail.lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


def preview_tail(text: str, max_chars: int) -> str:
    """Live preview of streaming text: nothing under 50 chars, drop the last (unfinished) word,
    keep at most max_chars from the end."""
    if len(text) < PREVIEW_MIN_CHARS:
        return ""
    shown = text
    if not shown.endswith(("\n", " ")):
        idx = max(shown.rfind(" "), shown.rfind("\n"))
        if idx > 0:
            shown = shown[:idx]
    if len(shown) > max_chars:
        shown = "…" + shown[-max_chars:]
    return shown


def format_duration(ms: int | None) -> str:
    if not ms:
        return "0 с"
    secs = int(ms / 1000)
    m, s = divmod(secs, 60)
    return f"{m} м {s} с" if m else f"{s} с"


def format_clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
