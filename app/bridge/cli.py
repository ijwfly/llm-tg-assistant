"""Command line and environment for a topic's `claude` process."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import settings

MCP_SERVER = Path(__file__).resolve().parent / "mcp_server.py"
PREAMBLE = Path(__file__).resolve().parents[2] / "bridge_preamble.md"
PROMPT_TOOL = "mcp__tgbridge__approve"
PROMPT_MODES = {"prompt", "acceptEdits", "plan", "auto"}   # bridge modes that route questions to Telegram

# bridge permission mode -> --permission-mode value
PERMISSION_MODES = {
    "prompt": "default",
    "acceptEdits": "acceptEdits",
    "plan": "plan",
    "auto": "auto",
    "dontAsk": "dontAsk",
    "bypass": "bypassPermissions",
}

# environment keys that must never reach the model's shell
_STRIP_PREFIXES = ("CLAUDE_CODE_", "POSTGRES_")
_STRIP_KEYS = {"TELEGRAM_BOT_TOKEN", "DATABASE_URL", "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"}


def child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in _STRIP_KEYS and not k.startswith(_STRIP_PREFIXES)}
    if settings.CLAUDE_CONFIG_DIR:
        env["CLAUDE_CONFIG_DIR"] = settings.CLAUDE_CONFIG_DIR
    env.update(settings.CLAUDE_ENV)
    return env


def mcp_config(token: str) -> str:
    """Inline --mcp-config JSON for the bridge's prompt tool server."""
    timeout = max(settings.PERMISSION_TIMEOUT_SECS, settings.QUESTION_TIMEOUT_SECS) + 30
    return json.dumps({"mcpServers": {"tgbridge": {
        "command": sys.executable, "args": [str(MCP_SERVER)],
        "env": {"TGBRIDGE_SOCKET": settings.BRIDGE_SOCKET, "TGBRIDGE_TOKEN": token,
                "TGBRIDGE_TIMEOUT": str(int(timeout))}}}})


def soul_file(topic: dict) -> Path | None:
    """The persona file for a topic: its own path, or SOUL_PATH unless the topic said `off`."""
    raw = topic.get("soul_path")
    if raw == "off":
        return None
    candidate = raw or settings.SOUL_PATH
    if not candidate:
        return None
    path = Path(os.path.expanduser(candidate))
    return path if path.is_file() else None


def system_prompt_file(topic: dict) -> str | None:
    """Preamble + persona glued into one file per topic (one --append-system-prompt-file)."""
    parts = []
    preamble = Path(os.path.expanduser(settings.BRIDGE_PREAMBLE_PATH)) if settings.BRIDGE_PREAMBLE_PATH else PREAMBLE
    if preamble.is_file():
        parts.append(preamble.read_text())
    soul = soul_file(topic)
    if soul is not None:
        parts.append(soul.read_text())
    if not parts:
        return None
    out_dir = Path(settings.INBOX_DIR) / "system"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"topic-{topic['id']}.md"
    path.write_text("\n\n".join(p.strip() for p in parts) + "\n")
    return str(path)


def uses_prompt_tool(topic: dict) -> bool:
    return (topic.get("permission_mode") or settings.DEFAULT_PERMISSION_MODE) in PROMPT_MODES


def build_argv(topic: dict, *, resume: bool, prompt_token: str | None = None) -> list[str]:
    mode = PERMISSION_MODES.get(topic.get("permission_mode") or settings.DEFAULT_PERMISSION_MODE, "default")
    argv = [settings.CLAUDE_BIN, "-p", "--verbose",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--replay-user-messages",
            "--permission-mode", mode]
    if prompt_token and uses_prompt_tool(topic):
        argv += ["--permission-prompt-tool", PROMPT_TOOL, "--mcp-config", mcp_config(prompt_token)]
    if resume:
        argv += ["--resume", str(topic["session_id"])]
        fork = (topic.get("settings") or {}).get("fork")
        if fork:   # a branch topic: the first spawn forks the source session into a new id
            argv += ["--fork-session"]
            if fork.get("name"):
                argv += ["--name", fork["name"]]
    else:
        argv += ["--session-id", str(topic["session_id"])]
    if topic.get("model") and topic["model"] != "default":
        argv += ["--model", topic["model"]]
    if topic.get("effort") and topic["effort"] != "default":
        argv += ["--effort", topic["effort"]]
    system_prompt = system_prompt_file(topic)
    if system_prompt:
        argv += ["--append-system-prompt-file", system_prompt]
    if settings.FALLBACK_MODEL:
        argv += ["--fallback-model", settings.FALLBACK_MODEL]
    if settings.MAX_BUDGET_USD_PER_TURN:
        argv += ["--max-budget-usd", str(settings.MAX_BUDGET_USD_PER_TURN)]
    if settings.ALLOWED_TOOLS:
        argv += ["--allowed-tools", ",".join(settings.ALLOWED_TOOLS)]
    if settings.DISALLOWED_TOOLS:
        argv += ["--disallowed-tools", ",".join(settings.DISALLOWED_TOOLS)]
    if settings.CLAUDE_SETTINGS:
        argv += ["--settings", settings.CLAUDE_SETTINGS]
    for d in settings.ADD_DIRS:
        argv += ["--add-dir", d]
    return argv
