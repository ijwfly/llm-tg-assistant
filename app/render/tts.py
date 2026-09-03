"""Turn a markdown answer into prose worth reading aloud (PROJECT_SPEC 4.8)."""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+")
_HTML_RE = re.compile(r"<[^>\n]+>")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|~~|\|\|)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_SENTENCE_END = re.compile(r"[.!?…](?:\s|$)")


def speakable(markdown: str, limit: int = 900) -> str:
    """Prose only: code, tables, links and markup are dropped; cut at a sentence boundary."""
    text = _FENCE_RE.sub(" ", markdown)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if s.startswith("|") or set(s) <= set("-|: "):      # table rows and rules
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("", text)
    text = _HTML_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    last = None
    for m in _SENTENCE_END.finditer(head):
        last = m.end()
    return head[:last].strip() if last and last > limit // 3 else head.rsplit(" ", 1)[0].strip()
