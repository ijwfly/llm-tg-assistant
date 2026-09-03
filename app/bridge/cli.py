"""Command line and environment for a topic's `claude` process."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import settings

MCP_SERVER = Path(__file__).resolve().parent / "mcp_server.py"
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
    if topic.get("model"):
        argv += ["--model", topic["model"]]
    if topic.get("effort"):
        argv += ["--effort", topic["effort"]]
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
