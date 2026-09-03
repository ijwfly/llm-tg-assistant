import json
from pathlib import Path

from app.bridge.rules import Rule, always_rule, forget_rules, local_allow_rules, permission_update


def rule(tool, inp):
    r = always_rule(tool, inp)
    return r.text if r else None


def test_always_rule_matrix():
    assert rule("Read", {"file_path": "/x"}) == "Read"
    assert rule("Grep", {"pattern": "x"}) == "Grep"
    assert rule("Bash", {"command": "git status"}) == "Bash(git status *)"
    assert rule("Bash", {"command": "cargo test --workspace"}) == "Bash(cargo test *)"
    assert rule("Bash", {"command": "ls -la"}) == "Bash(ls -la)"
    assert rule("Bash", {"command": "npm --version"}) == "Bash(npm --version)"
    assert rule("Bash", {"command": "rm -rf build"}) is None
    assert rule("Bash", {"command": "sudo apt install x"}) is None
    assert rule("Bash", {"command": "cat a | grep b"}) is None
    assert rule("Bash", {"command": "make && make test"}) is None
    assert rule("Bash", {"command": "echo a\necho b"}) is None
    assert rule("Bash", {"command": "x" * 130}) is None
    assert rule("Bash", {"command": ""}) is None
    assert rule("WebFetch", {"url": "https://docs.python.org/3/library/asyncio.html"}) == "WebFetch(domain:docs.python.org)"
    assert rule("WebFetch", {"url": "nope"}) is None
    assert rule("mcp__github__create_issue", {}) == "mcp__github__create_issue"
    assert rule("mcp__tgbridge__approve", {}) is None
    for tool in ("Edit", "Write", "NotebookEdit", "MultiEdit", "AskUserQuestion", "ExitPlanMode", "Task"):
        assert rule(tool, {"file_path": "/x"}) is None


def test_permission_update_shape():
    assert permission_update(Rule("Bash", "git status *")) == {
        "type": "addRules", "behavior": "allow", "destination": "localSettings",
        "rules": [{"toolName": "Bash", "ruleContent": "git status *"}]}
    assert permission_update(Rule("Read"))["rules"] == [{"toolName": "Read"}]


def test_forget_rules_walks_up_to_the_work_root(tmp_path: Path):
    root = tmp_path / "work"
    proj = root / "proj" / "sub"
    proj.mkdir(parents=True)
    for d, allow in ((root / "proj", ["Bash(git status *)", "Read"]), (proj, ["Bash(git status *)"]),
                     (tmp_path, ["Bash(git status *)"])):   # tmp_path is above the root: untouched
        (d / ".claude").mkdir(exist_ok=True)
        (d / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"allow": allow}}))
    assert sorted(local_allow_rules(str(proj), str(root))) == ["Bash(git status *)", "Bash(git status *)", "Read"]
    assert forget_rules(str(proj), str(root), ["Bash(git status *)"]) == 2
    assert json.loads((root / "proj" / ".claude" / "settings.local.json").read_text())["permissions"]["allow"] == ["Read"]
    assert json.loads((tmp_path / ".claude" / "settings.local.json").read_text())["permissions"]["allow"] == ["Bash(git status *)"]
    assert forget_rules(str(proj), str(root), ["Bash(git status *)"]) == 0
