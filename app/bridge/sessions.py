"""Read-only index of Claude Code sessions from the transcript directory (no process needed).

Layout and title rules mirror claude-agent-sdk 0.2.152 `_internal/sessions.py`:
`$CLAUDE_CONFIG_DIR/projects/<sanitized cwd>/<session-id>.jsonl`; title = customTitle > aiTitle >
lastPrompt > summary > first meaningful user prompt. Only the head and tail of a file are read.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import settings

HEAD_BYTES = 64 * 1024
TAIL_BYTES = 16 * 1024
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]")
_COMMAND_RE = re.compile(r"<command-name>([^<]+)</command-name>")
_SKIP_RE = re.compile(r"^(<local-command|<system-|\[Request interrupted)")


@dataclass
class SessionInfo:
    session_id: str
    title: str
    mtime: float
    cwd: str | None
    custom_title: str | None = None
    path: Path | None = None

    @property
    def short(self) -> str:
        return self.session_id[:8]


def config_dir() -> Path:
    raw = settings.CLAUDE_CONFIG_DIR or os.path.join(os.path.expanduser("~"), ".claude")
    return Path(unicodedata.normalize("NFC", raw))


def sanitize_cwd(cwd: str) -> str:
    return _SANITIZE_RE.sub("-", unicodedata.normalize("NFC", os.path.realpath(cwd)))


def project_dir(cwd: str) -> Path:
    return config_dir() / "projects" / sanitize_cwd(cwd)


def _last_string_field(text: str, key: str) -> str | None:
    """Last value of a top-level-looking `"key":"value"` pair in the text (no full parse)."""
    needle = f'"{key}":'
    pos = text.rfind(needle)
    while pos >= 0:
        rest = text[pos + len(needle):].lstrip()
        if rest.startswith('"'):
            try:
                value, _ = json.JSONDecoder().raw_decode(rest)
                if isinstance(value, str) and value.strip():
                    return value
            except json.JSONDecodeError:
                pass
        pos = text.rfind(needle, 0, pos)
    return None


def _flag(line: str, key: str) -> bool:
    return f'"{key}":true' in line or f'"{key}": true' in line


def _first_prompt(head: str) -> str | None:
    fallback = None
    for line in head.split("\n"):
        if '"type":"user"' not in line and '"type": "user"' not in line:
            continue
        if '"tool_result"' in line or _flag(line, "isMeta") or _flag(line, "isCompactSummary"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue   # truncated last line of the head
        if entry.get("type") != "user" or not isinstance(entry.get("message"), dict):
            continue
        content = entry["message"].get("content")
        texts = [content] if isinstance(content, str) else [
            b.get("text") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
        for raw in texts:
            text = (raw or "").replace("\n", " ").strip()
            if not text:
                continue
            m = _COMMAND_RE.search(text)
            if m:
                fallback = fallback or m.group(1)
                continue
            if _SKIP_RE.match(text):
                continue
            return text[:200].rstrip() + ("…" if len(text) > 200 else "")
    return fallback


def read_session(path: Path) -> SessionInfo | None:
    try:
        size = path.stat().st_size
        mtime = path.stat().st_mtime
        with path.open("rb") as f:
            head = f.read(HEAD_BYTES).decode("utf-8", errors="replace")
            if size > HEAD_BYTES:
                f.seek(max(size - TAIL_BYTES, 0))
                tail = f.read().decode("utf-8", errors="replace")
            else:
                tail = head
    except OSError:
        return None
    first_line = head.split("\n", 1)[0]
    if '"isSidechain":true' in first_line or '"isSidechain": true' in first_line:
        return None
    custom = (_last_string_field(tail, "customTitle") or _last_string_field(head, "customTitle")
              or _last_string_field(tail, "aiTitle") or _last_string_field(head, "aiTitle"))
    title = (custom or _last_string_field(tail, "lastPrompt") or _last_string_field(tail, "summary")
             or _first_prompt(head))
    if not title:
        return None
    cwd = _first_string_field(head, "cwd")
    return SessionInfo(path.stem, title, mtime, cwd, custom_title=custom, path=path)


def _first_string_field(text: str, key: str) -> str | None:
    needle = f'"{key}":'
    pos = text.find(needle)
    while pos >= 0:
        rest = text[pos + len(needle):].lstrip()
        if rest.startswith('"'):
            try:
                value, _ = json.JSONDecoder().raw_decode(rest)
                if isinstance(value, str) and value:
                    return value
            except json.JSONDecodeError:
                pass
        pos = text.find(needle, pos + 1)
    return None


def _sessions_in(directory: Path) -> list[SessionInfo]:
    out = []
    try:
        files = [p for p in directory.iterdir() if p.suffix == ".jsonl" and UUID_RE.match(p.stem)]
    except OSError:
        return out
    for path in files:
        info = read_session(path)
        if info:
            out.append(info)
    return out


def list_sessions(cwd: str, limit: int = 8) -> list[SessionInfo]:
    """Sessions of one project directory, newest first."""
    infos = _sessions_in(project_dir(cwd))
    infos.sort(key=lambda s: s.mtime, reverse=True)
    return infos[:limit]


def all_sessions() -> list[SessionInfo]:
    root = config_dir() / "projects"
    out: list[SessionInfo] = []
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        out.extend(_sessions_in(d))
    out.sort(key=lambda s: s.mtime, reverse=True)
    return out


def find_sessions(query: str, cwd: str | None = None) -> list[SessionInfo]:
    """Match by full id, id prefix (>= 4 chars) or custom title (case-insensitive). The topic's own
    directory is searched first, then every project. Returns all matches (ambiguity is the caller's)."""
    q = query.strip()
    if not q:
        return []
    candidates = (list_sessions(cwd, limit=1000) if cwd else []) + all_sessions()
    seen: set[str] = set()
    matches = []
    for s in candidates:
        if s.session_id in seen:
            continue
        seen.add(s.session_id)
        if s.session_id == q.lower() or (len(q) >= 4 and s.session_id.startswith(q.lower())):
            matches.append(s)
        elif s.custom_title and s.custom_title.strip().lower() == q.lower():
            matches.append(s)
    exact = [s for s in matches if s.session_id == q.lower()]
    return exact or matches


def session_title(session_id: str | None, cwd: str) -> str | None:
    if not session_id:
        return None
    path = project_dir(cwd) / f"{session_id}.jsonl"
    if not path.is_file():
        return None
    info = read_session(path)
    return info.title if info else None


def ago(mtime: float, now: float | None = None) -> str:
    delta = max(0, int((now or time.time()) - mtime))
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{delta // 60} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    return f"{delta // 86400} дн назад"
