"""The bridge MCP server runs as a separate process from any cwd; tests drive it over stdio."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "app" / "bridge" / "mcp_server.py"


def rpc(proc, msg_id, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def start(env):
    return subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            env={**env, "PATH": os.environ.get("PATH", "")}, cwd=tempfile.gettempdir())


def test_initialize_and_tools_list(tmp_path):
    proc = start({"TGBRIDGE_SOCKET": str(tmp_path / "none.sock"), "TGBRIDGE_TOKEN": "t"})
    try:
        init = rpc(proc, 1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})
        assert init["result"]["serverInfo"]["name"] == "tgbridge" and init["result"]["protocolVersion"] == "2025-11-25"
        tools = rpc(proc, 2, "tools/list")["result"]["tools"]
        assert [t["name"] for t in tools] == ["approve"]
        assert rpc(proc, 3, "ping")["result"] == {}
        assert "error" in rpc(proc, 4, "nope")
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
        proc.stdout.close()


def test_missing_daemon_is_a_deny_not_a_hang(tmp_path):
    proc = start({"TGBRIDGE_SOCKET": str(tmp_path / "none.sock"), "TGBRIDGE_TOKEN": "t", "TGBRIDGE_TIMEOUT": "2"})
    try:
        resp = rpc(proc, 1, "tools/call", {"name": "approve", "arguments": {"tool_name": "Bash", "input": {"command": "ls"}}})
        decision = json.loads(resp["result"]["content"][0]["text"])
        assert decision["behavior"] == "deny" and "Telegram bridge unavailable" in decision["message"]
        assert "error" in rpc(proc, 2, "tools/call", {"name": "other", "arguments": {}})
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
        proc.stdout.close()


def test_daemon_decision_is_proxied_with_the_token():
    sock_dir = tempfile.mkdtemp(prefix="tgb")
    path = os.path.join(sock_dir, "s.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    seen = {}

    def serve():
        conn, _ = server.accept()
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                data += conn.recv(4096)
            seen["request"] = json.loads(data)
            conn.sendall(b'{"behavior": "allow", "updatedInput": {"command": "ls"}}\n')

    threading.Thread(target=serve, daemon=True).start()
    proc = start({"TGBRIDGE_SOCKET": path, "TGBRIDGE_TOKEN": "secret-token"})
    try:
        resp = rpc(proc, 1, "tools/call", {"name": "approve", "arguments": {"tool_name": "Bash", "input": {"command": "ls"},
                                                                            "tool_use_id": "toolu_9"}})
        assert json.loads(resp["result"]["content"][0]["text"]) == {"behavior": "allow", "updatedInput": {"command": "ls"}}
        assert seen["request"] == {"token": "secret-token", "tool": "approve", "tool_use_id": "toolu_9",
                                   "args": {"tool_name": "Bash", "input": {"command": "ls"}, "tool_use_id": "toolu_9"}}
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
        proc.stdout.close()
        server.close()
        os.unlink(path)
        os.rmdir(sock_dir)
