"""Fixture helper around tests/fake_claude/claude: scenarios in, argv/stdin log out."""
from __future__ import annotations

import json
import itertools
from pathlib import Path

FAKE_BIN = Path(__file__).resolve().parents[1] / "fake_claude" / "claude"


def assistant_text(text: str) -> dict:
    return {"type": "assistant", "session_id": "{session_id}",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def result(*, subtype: str = "success", is_error: bool = False, text: str | None = None, session_id: str = "{session_id}",
           denials: list | None = None, cost: float = 0.01, num_turns: int = 1, duration_ms: int = 1200) -> dict:
    return {"type": "result", "subtype": subtype, "is_error": is_error, "result": text, "session_id": session_id,
            "duration_ms": duration_ms, "num_turns": num_turns, "total_cost_usd": cost,
            "usage": {"input_tokens": 10, "output_tokens": 20}, "permission_denials": denials or []}


def text_delta(text: str) -> dict:
    return {"type": "stream_event", "session_id": "{session_id}",
            "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}}


def thinking_delta(text: str) -> dict:
    return {"type": "stream_event", "session_id": "{session_id}",
            "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": text}}}


def tool_use(name: str, tool_input: dict, tool_id: str = "toolu_1", parent: str | None = None) -> dict:
    return {"type": "assistant", "session_id": "{session_id}", "parent_tool_use_id": parent,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]}}


def tool_result(tool_id: str = "toolu_1", content: str = "ok") -> dict:
    return {"type": "user", "session_id": "{session_id}",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]}}


def compact_boundary(pre_tokens: int = 1842) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "session_id": "{session_id}",
            "compact_metadata": {"pre_tokens": pre_tokens, "trigger": "manual"}}


def permission_denied(tool: str) -> dict:
    return {"type": "system", "subtype": "permission_denied", "tool_name": tool, "tool_use_id": "toolu_1",
            "decision_reason": "no approval surface", "session_id": "{session_id}"}


def prompt_tool(tool_name: str, tool_input: dict, tool_use_id: str = "toolu_1") -> dict:
    """Scenario step: the fake really calls the bridge MCP server and blocks until the decision."""
    return {"prompt_tool": {"tool_name": tool_name, "input": tool_input, "tool_use_id": tool_use_id}}


def mcp_tool(name: str, arguments: dict | None = None) -> dict:
    """Scenario step: call any tool of the bridge MCP server (e.g. send_file); `list` lists the tools."""
    return {"mcp_tool": {"name": name, "arguments": arguments or {}}}


def question(*questions: dict) -> dict:
    return {"questions": list(questions)}


def q(text: str, *options: str, header: str = "Вопрос", multi: bool = False, descriptions: dict | None = None) -> dict:
    descriptions = descriptions or {}
    return {"question": text, "header": header, "multiSelect": multi,
            "options": [{"label": o, "description": descriptions.get(o, "")} for o in options]}


def write_transcript(config_dir: str, cwd: str, session_id: str, prompts: list[str], *, custom_title: str | None = None,
                     ai_title: str | None = None, summary: str | None = None, mtime: float | None = None,
                     sidechain: bool = False) -> Path:
    """A minimal Claude Code transcript in the shape the session index reads."""
    from app.bridge.sessions import sanitize_cwd
    directory = Path(config_dir) / "projects" / sanitize_cwd(cwd)
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, p in enumerate(prompts):
        entry = {"type": "user", "uuid": f"u{i}", "sessionId": session_id, "cwd": cwd,
                 "timestamp": "2026-09-03T10:00:00.000Z",
                 "message": {"role": "user", "content": p}}
        if sidechain and i == 0:
            entry["isSidechain"] = True
        lines.append(json.dumps(entry, ensure_ascii=False))
        lines.append(json.dumps({"type": "assistant", "uuid": f"a{i}", "sessionId": session_id,
                                 "message": {"role": "assistant", "content": [{"type": "text", "text": f"ответ {i}"}]}},
                                ensure_ascii=False))
    if summary:
        lines.append(json.dumps({"type": "summary", "summary": summary, "leafUuid": "a0"}, ensure_ascii=False))
    if ai_title:
        lines.append(json.dumps({"type": "ai-title", "aiTitle": ai_title, "sessionId": session_id}, ensure_ascii=False))
    if custom_title:
        lines.append(json.dumps({"type": "custom-title", "customTitle": custom_title, "sessionId": session_id}, ensure_ascii=False))
    path = directory / f"{session_id}.jsonl"
    path.write_text("\n".join(lines) + "\n")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


class FakeClaude:
    def __init__(self, root: Path):
        self.scenarios = root / "scenarios"
        self.scenarios.mkdir()
        self.log_path = root / "claude.log"
        self._seq = itertools.count(1)

    @property
    def env(self) -> dict[str, str]:
        return {"FAKE_CLAUDE_SCENARIOS": str(self.scenarios), "FAKE_CLAUDE_LOG": str(self.log_path)}

    def enqueue(self, *events: dict) -> None:
        (self.scenarios / f"{next(self._seq):03d}.json").write_text(json.dumps({"events": list(events)}))

    def text_turn(self, text: str, **kw) -> None:
        self.enqueue(assistant_text(text), result(**kw))

    def log(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(l) for l in self.log_path.read_text().splitlines() if l.strip()]

    def argv_calls(self) -> list[list[str]]:
        return [rec["argv"] for rec in self.log() if "argv" in rec]

    def cwds(self) -> list[str]:
        return [rec["cwd"] for rec in self.log() if "argv" in rec]

    def stdin_texts(self) -> list[str]:
        out = []
        for rec in self.log():
            msg = rec.get("stdin")
            if not msg:
                continue
            content = msg.get("message", {}).get("content")
            if isinstance(content, str):
                out.append(content)
            else:
                out.append("\n".join(b.get("text", "") for b in content if b.get("type") == "text"))
        return out

    def mcp_results(self) -> list[dict]:
        return [rec["mcp_result"] for rec in self.log() if "mcp_result" in rec]

    def mcp_tools(self) -> list[list[str]]:
        return [rec["mcp_tools"] for rec in self.log() if "mcp_tools" in rec]

    def user_uuids(self) -> list[str]:
        return [rec["user_uuid"] for rec in self.log() if "user_uuid" in rec]

    def rewinds(self) -> list[dict]:
        return [rec for rec in self.log() if "rewind" in rec]

    def decisions(self) -> list[dict]:
        """Decisions the prompt tool returned, in order."""
        return [rec["prompt_decision"] for rec in self.log() if "prompt_decision" in rec]

    def signals(self) -> list[str]:
        return [rec["signal"] for rec in self.log() if "signal" in rec]
