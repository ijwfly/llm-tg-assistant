#!/usr/bin/env python3
"""Spike MCP server for `--permission-prompt-tool`.

Stdio JSON-RPC (newline-delimited). Logs every request to $SPIKE_LOG and answers
`tools/call` according to the policy JSON at $SPIKE_POLICY:

    {
      "default": {"behavior": "allow"},
      "Bash": {"behavior": "allow",
               "updatedPermissions": [{"type": "addRules", "behavior": "allow",
                                       "destination": "session",
                                       "rules": [{"toolName": "Bash", "ruleContent": "echo *"}]}]},
      "AskUserQuestion": {"behavior": "allow", "answer_index": 0},
      "ExitPlanMode": {"behavior": "allow",
                       "updatedPermissions": [{"type": "setMode", "mode": "acceptEdits",
                                               "destination": "session"}]},
      "Write": {"behavior": "deny", "message": "spike: denied"}
    }

Stdlib only, so it can be launched by `claude` from any environment.
"""
import json
import os
import sys
import time

LOG = os.environ.get("SPIKE_LOG", "/tmp/spike_mcp.log")
POLICY = os.environ.get("SPIKE_POLICY")


def log(obj):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **obj}, ensure_ascii=False) + "\n")


def load_policy():
    if POLICY and os.path.exists(POLICY):
        with open(POLICY) as f:
            return json.load(f)
    return {}


def decide(args):
    policy = load_policy()
    tool_name = args.get("tool_name")
    inp = args.get("input") or {}
    rule = policy.get(tool_name) or policy.get("default") or {"behavior": "allow"}
    resp = dict(rule)
    answer_index = resp.pop("answer_index", 0)
    if resp.get("behavior") == "allow":
        if tool_name == "AskUserQuestion":
            answers = {}
            for q in inp.get("questions", []):
                opts = q.get("options", [])
                if q.get("multiSelect"):
                    answers[q["question"]] = [o["label"] for o in opts[:2]]
                else:
                    answers[q["question"]] = opts[answer_index]["label"] if opts else "yes"
            resp["updatedInput"] = {"questions": inp.get("questions", []), "answers": answers}
        elif "updatedInput" not in resp:
            resp["updatedInput"] = inp
    return resp


TOOLS = [
    {
        "name": "approve",
        "description": "Permission prompt handler (spike)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string"},
                "input": {"type": "object"},
                "tool_use_id": {"type": "string"},
            },
            "required": ["tool_name", "input"],
            "additionalProperties": True,
        },
    },
    {
        "name": "send_file",
        "description": "Send a file from the working directory to the chat (spike: logs only)",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "caption": {"type": "string"}},
            "required": ["path"],
        },
    },
]


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main():
    log({"event": "server_start", "argv": sys.argv, "cwd": os.getcwd()})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log({"event": "bad_json", "line": line[:500]})
            continue
        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}
        log({"event": "request", "method": method, "id": msg_id, "params": params})
        if msg_id is None:
            continue  # notification
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tgbridge-spike", "version": "0.0.1"},
            })
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "approve":
                resp = decide(args)
                log({"event": "approve_response", "tool_name": args.get("tool_name"), "response": resp})
                reply(msg_id, {"content": [{"type": "text", "text": json.dumps(resp)}]})
            elif name == "send_file":
                reply(msg_id, {"content": [{"type": "text", "text": f"File {args.get('path')} sent (spike)"}]})
            else:
                reply(msg_id, error={"code": -32602, "message": f"unknown tool {name}"})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})
    log({"event": "server_exit"})


if __name__ == "__main__":
    main()
