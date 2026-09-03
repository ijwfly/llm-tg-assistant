"""Permission, question and plan cards (PROJECT_SPEC 4.6.2, 4.7). Pure rendering, no I/O except
reading the target file of a Write for its diff."""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import settings

SECRET_KEY_RE = re.compile(r"token|secret|password|passwd|api[_-]?key|authorization|cookie", re.I)
JSON_LIMIT = 700
WRITE_HEAD_LINES = 40
OPTION_LABEL_LIMIT = 60
LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx", ".rs": "rust",
         ".go": "go", ".rb": "ruby", ".sh": "bash", ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
         ".md": "markdown", ".html": "html", ".css": "css", ".sql": "sql", ".java": "java", ".kt": "kotlin",
         ".c": "c", ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".swift": "swift", ".php": "php"}


def mask_secrets(value):
    if isinstance(value, dict):
        return {k: ("•••" if SECRET_KEY_RE.search(str(k)) and isinstance(v, (str, int, float)) else mask_secrets(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


def fence(body: str, lang: str = "") -> str:
    """A code fence that cannot be closed by the body itself."""
    ticks = "```"
    while ticks in body:
        ticks += "`"
    return f"{ticks}{lang}\n{body.rstrip()}\n{ticks}"


def _lang(path: str) -> str:
    return LANGS.get(Path(path).suffix.lower(), "")


def diff_block(old: str, new: str, path: str, limit: int | None = None) -> str:
    limit = limit or settings.PERMISSION_DIFF_LINES
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=path, tofile=path, lineterm="", n=2))
    if len(lines) > limit:
        lines = lines[:limit] + [f"… ещё {len(lines) - limit} строк"]
    return fence("\n".join(lines), "diff")


def _short(path: str, cwd: str | None) -> str:
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return path


def _existing(path: str) -> str | None:
    try:
        p = Path(path)
        if p.is_file() and p.stat().st_size <= 512 * 1024:
            return p.read_text(errors="replace")
    except OSError:
        pass
    return None


def permission_card(tool_name: str, tool_input: dict, cwd: str | None = None) -> str:
    head = f"🔐 **{tool_name}** просит разрешение"
    inp = tool_input or {}
    if tool_name == "Bash":
        body = fence(str(inp.get("command") or ""), "bash")
        if inp.get("description"):
            body += f"\n_{inp['description']}_"
        return f"{head}\n{body}"
    if tool_name in ("Edit", "MultiEdit"):
        path = str(inp.get("file_path") or "?")
        if tool_name == "MultiEdit":
            edits = inp.get("edits") or []
            parts = [diff_block(str(e.get("old_string", "")), str(e.get("new_string", "")), path) for e in edits[:5]]
            return f"{head}\n`{_short(path, cwd)}` ({len(edits)} правок)\n" + "\n".join(parts)
        return f"{head}\n`{_short(path, cwd)}`\n" + diff_block(str(inp.get("old_string", "")), str(inp.get("new_string", "")), path)
    if tool_name == "Write":
        path = str(inp.get("file_path") or "?")
        content = str(inp.get("content") or "")
        existing = _existing(path)
        size = f"{len(content.encode())} B"
        if existing is not None:
            return f"{head}\n`{_short(path, cwd)}` (перезапись, {size})\n" + diff_block(existing, content, path)
        lines = content.splitlines()
        shown = "\n".join(lines[:WRITE_HEAD_LINES])
        if len(lines) > WRITE_HEAD_LINES:
            shown += f"\n… ещё {len(lines) - WRITE_HEAD_LINES} строк"
        return f"{head}\n`{_short(path, cwd)}` (новый файл, {size})\n" + fence(shown, _lang(path))
    if tool_name == "NotebookEdit":
        path = str(inp.get("notebook_path") or "?")
        cell = inp.get("cell_id") or inp.get("cell_number") or "?"
        return f"{head}\n`{_short(path, cwd)}` · ячейка {cell} · {inp.get('edit_mode') or 'replace'}\n" + \
            fence(str(inp.get("new_source") or ""), "python")
    if tool_name in ("Read", "Glob", "Grep", "LS", "NotebookRead"):
        detail = inp.get("file_path") or inp.get("notebook_path") or inp.get("pattern") or inp.get("path") or ""
        extra = f" в `{_short(str(inp['path']), cwd)}`" if tool_name in ("Glob", "Grep") and inp.get("path") else ""
        return f"{head}\n`{_short(str(detail), cwd)}`{extra}"
    if tool_name == "WebFetch":
        return f"{head}\n{inp.get('url') or ''}"
    if tool_name == "WebSearch":
        return f"{head}\n«{inp.get('query') or ''}»"
    text = json.dumps(mask_secrets(inp), ensure_ascii=False, indent=1)
    if len(text) > JSON_LIMIT:
        text = text[:JSON_LIMIT] + "…"
    return f"{head}\n" + fence(text, "json")


def option_label(option: dict) -> str:
    label = str(option.get("label") or "")
    desc = str(option.get("description") or "")
    text = f"{label} — {desc}" if desc else label
    return text if len(text) <= OPTION_LABEL_LIMIT else text[:OPTION_LABEL_LIMIT - 1] + "…"


def question_card(question: dict, index: int, total: int) -> str:
    header = str(question.get("header") or "Вопрос")
    title = f"❓ {header} ({index + 1}/{total})" if total > 1 else f"❓ {header}"
    body = str(question.get("question") or "")
    if question.get("multiSelect"):
        body += "\n_(можно выбрать несколько)_"
    return f"{title}\n{body}"


def plan_card(plan: str) -> str:
    return "📋 **План готов**\n\n" + (plan.strip() or "_(пусто)_")
