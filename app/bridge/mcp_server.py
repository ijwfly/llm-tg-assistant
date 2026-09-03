#!/usr/bin/env python3
"""Bridge MCP server: Claude Code's `--permission-prompt-tool` (PROJECT_SPEC 6.5).

Launched by `claude` (config from `app/bridge/cli.py`), speaks newline-delimited JSON-RPC on
stdio and forwards every `tools/call approve` to the daemon over the unix socket `TGBRIDGE_SOCKET`
as one JSON line `{token, tool, tool_use_id, args}`; the daemon answers with one JSON line —
the decision object Claude Code expects (`{"behavior": …}`). Stdlib only: it runs from any cwd
with the daemon's interpreter and never imports the application.
"""
import json
import os
import socket
import sys

SOCKET = os.environ.get("TGBRIDGE_SOCKET", "")
TOKEN = os.environ.get("TGBRIDGE_TOKEN", "")
TIMEOUT = float(os.environ.get("TGBRIDGE_TIMEOUT", "1900"))

TOOLS = [{
    "name": "approve",
    "description": "Telegram bridge permission prompt: asks the user in the chat and returns the decision.",
    "inputSchema": {
        "type": "object",
        "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"],
        "additionalProperties": True,
    },
}]


def deny(message: str) -> dict:
    return {"behavior": "deny", "message": message}


def ask_daemon(args: dict) -> dict:
    """One request, one reply. Any failure is a deny with the reason, so the tool never hangs forever."""
    request = {"token": TOKEN, "tool": "approve", "tool_use_id": args.get("tool_use_id"), "args": args}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(TIMEOUT)
            s.connect(SOCKET)
            s.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except (OSError, socket.timeout) as e:
        return deny(f"Telegram bridge unavailable: {e.__class__.__name__}: {e}")
    if not buf.strip():
        return deny("Telegram bridge closed the connection without a decision")
    try:
        return json.loads(buf)
    except json.JSONDecodeError:
        return deny("Telegram bridge returned an unreadable decision")


def reply(msg_id, result=None, error=None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id, params = req.get("method"), req.get("id"), req.get("params") or {}
        if msg_id is None:
            continue  # notification
        if method == "initialize":
            reply(msg_id, {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                           "capabilities": {"tools": {}}, "serverInfo": {"name": "tgbridge", "version": "1"}})
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            if params.get("name") != "approve":
                reply(msg_id, error={"code": -32602, "message": f"unknown tool {params.get('name')}"})
                continue
            decision = ask_daemon(params.get("arguments") or {})
            reply(msg_id, {"content": [{"type": "text", "text": json.dumps(decision, ensure_ascii=False)}]})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
