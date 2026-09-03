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


def compact_boundary(pre_tokens: int = 1842) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "session_id": "{session_id}",
            "compact_metadata": {"pre_tokens": pre_tokens, "trigger": "manual"}}


def permission_denied(tool: str) -> dict:
    return {"type": "system", "subtype": "permission_denied", "tool_name": tool, "tool_use_id": "toolu_1",
            "decision_reason": "no approval surface", "session_id": "{session_id}"}


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

    def signals(self) -> list[str]:
        return [rec["signal"] for rec in self.log() if "signal" in rec]
