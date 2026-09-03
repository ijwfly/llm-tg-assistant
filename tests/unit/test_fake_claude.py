import json
import subprocess
import sys
from pathlib import Path

FAKE = Path(__file__).resolve().parents[1] / "fake_claude" / "claude"


def _scenario(text: str) -> dict:
    return {"events": [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
         "session_id": "{session_id}"},
        {"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": "{session_id}",
         "duration_ms": 5, "num_turns": 1, "total_cost_usd": 0.001, "permission_denials": []},
    ]}


def _run(tmp_path, scenarios, argv, stdin_lines):
    scen_dir = tmp_path / "scen"
    scen_dir.mkdir(exist_ok=True)
    for i, s in enumerate(scenarios):
        (scen_dir / f"{i:03d}.json").write_text(json.dumps(s))
    log = tmp_path / "log.jsonl"
    proc = subprocess.run([sys.executable, str(FAKE), *argv], input="".join(stdin_lines), capture_output=True,
                          text=True, env={"FAKE_CLAUDE_SCENARIOS": str(scen_dir), "FAKE_CLAUDE_LOG": str(log),
                                          "PATH": "/usr/bin:/bin"}, timeout=20)
    events = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    log_lines = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return proc, events, log_lines


def _user(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n"


def test_fake_claude_replays_scenario_with_session_id(tmp_path):
    proc, events, log = _run(tmp_path, [_scenario("hello")],
                             ["-p", "--session-id", "abc-123", "--permission-mode", "manual"], [_user("hi")])
    assert proc.returncode == 0, proc.stderr
    assert events[0]["type"] == "system" and events[0]["session_id"] == "abc-123"
    assert events[-1]["type"] == "result" and events[-1]["result"] == "hello"
    assert events[-1]["session_id"] == "abc-123"
    assert log[0]["argv"][:3] == ["-p", "--session-id", "abc-123"]
    assert any(l.get("stdin", {}).get("message", {}).get("content") == "hi" for l in log)


def test_fake_claude_exhausted_queue_exits_with_3(tmp_path):
    proc, events, _ = _run(tmp_path, [_scenario("one")], ["-p", "--resume", "r-1"], [_user("a"), _user("b")])
    assert proc.returncode == 3
    assert "no scenario left" in proc.stderr
    assert sum(1 for e in events if e["type"] == "result") == 1
    assert events[0]["session_id"] == "r-1"
