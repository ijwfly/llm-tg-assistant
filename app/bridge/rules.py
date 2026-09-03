"""Permission rules for the "Always" button (PROJECT_SPEC 4.6.3) and their removal."""
from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

WHOLE_TOOL = {"Read", "Grep", "Glob", "WebSearch", "NotebookRead", "TodoWrite", "TaskCreate", "TaskUpdate",
              "TaskList", "TaskGet", "LS"}
NEVER = {"Edit", "Write", "NotebookEdit", "MultiEdit", "AskUserQuestion", "ExitPlanMode"}
SUBCOMMAND_PROGRAMS = {"git", "npm", "npx", "pnpm", "yarn", "bun", "cargo", "docker", "make", "pytest", "uv", "pip",
                       "poetry", "go", "gh", "kubectl", "helm", "terraform", "gradle", "mvn", "dotnet", "rustup",
                       "brew", "apt", "systemctl", "just"}
DANGEROUS = {"rm", "sudo", "curl", "wget", "dd", "mkfs", "chmod", "chown", "kill", "pkill", "shutdown", "reboot"}
BASH_MAX = 120


@dataclass(frozen=True)
class Rule:
    tool_name: str
    rule_content: str | None = None

    @property
    def text(self) -> str:
        return f"{self.tool_name}({self.rule_content})" if self.rule_content else self.tool_name

    def as_permission(self) -> dict:
        rule = {"toolName": self.tool_name}
        if self.rule_content:
            rule["ruleContent"] = self.rule_content
        return rule


def _bash_rule(command: str) -> Rule | None:
    cmd = command.strip()
    if not cmd or "\n" in cmd or len(cmd) > BASH_MAX:
        return None
    if any(op in cmd for op in ("&&", "||", "|", ";", "`", "$(", ">", "<")):
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    if not words or words[0] in DANGEROUS:
        return None
    if words[0] in SUBCOMMAND_PROGRAMS and len(words) > 1 and not words[1].startswith("-"):
        return Rule("Bash", f"{words[0]} {words[1]} *")
    return Rule("Bash", cmd)


def always_rule(tool_name: str, tool_input: dict) -> Rule | None:
    """The rule offered by the "Always" button, or None when the button must not appear."""
    if tool_name in NEVER:
        return None
    if tool_name in WHOLE_TOOL:
        return Rule(tool_name)
    if tool_name == "Bash":
        return _bash_rule(str(tool_input.get("command") or ""))
    if tool_name == "WebFetch":
        host = urlsplit(str(tool_input.get("url") or "")).hostname
        return Rule("WebFetch", f"domain:{host}") if host else None
    if tool_name.startswith("mcp__"):
        return None if tool_name.startswith("mcp__tgbridge__") else Rule(tool_name)
    return None


def permission_update(rule: Rule) -> dict:
    return {"type": "addRules", "behavior": "allow", "destination": "localSettings", "rules": [rule.as_permission()]}


def settings_files(cwd: str, root: str) -> list[Path]:
    """`.claude/settings.local.json` in cwd and its parents up to and including the work root."""
    out = []
    path = Path(cwd).resolve()
    root_path = Path(root).resolve()
    for d in [path, *path.parents]:
        candidate = d / ".claude" / "settings.local.json"
        if candidate.is_file():
            out.append(candidate)
        if d == root_path:
            break
    return out


def forget_rules(cwd: str, root: str, rules: list[str]) -> int:
    """Remove `rules` from the allow lists of the local settings files. Returns removed count."""
    removed = 0
    wanted = set(rules)
    for file in settings_files(cwd, root):
        try:
            data = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        allow = (data.get("permissions") or {}).get("allow")
        if not isinstance(allow, list):
            continue
        kept = [r for r in allow if r not in wanted]
        if len(kept) != len(allow):
            removed += len(allow) - len(kept)
            data["permissions"]["allow"] = kept
            file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return removed


def local_allow_rules(cwd: str, root: str) -> list[str]:
    out: list[str] = []
    for file in settings_files(cwd, root):
        try:
            allow = (json.loads(file.read_text()).get("permissions") or {}).get("allow") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        out.extend(str(r) for r in allow)
    return out
