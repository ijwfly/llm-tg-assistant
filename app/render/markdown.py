"""Text splitting for Telegram limits. Phase 2: line-based; phase 3 makes it fence-aware."""
from __future__ import annotations

RICH_LIMIT = 30_000
PLAIN_LIMIT = 4_000


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


def format_duration(ms: int | None) -> str:
    if not ms:
        return "0 с"
    secs = int(ms / 1000)
    m, s = divmod(secs, 60)
    return f"{m} м {s} с" if m else f"{s} с"
