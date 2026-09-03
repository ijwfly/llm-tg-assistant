import json
import time
from pathlib import Path

import settings
from app.bridge import sessions
from tests.support.fake_claude import write_transcript

S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"
S3 = "33333333-3333-4333-8333-333333333333"


def setup_config(tmp_path: Path) -> str:
    settings.CLAUDE_CONFIG_DIR = str(tmp_path / "claude")
    return settings.CLAUDE_CONFIG_DIR


def test_sanitize_cwd_replaces_non_alnum(tmp_path):
    assert sessions.sanitize_cwd("/Users/me/src/app") == "-Users-me-src-app"
    assert sessions.project_dir("/x/y").name == "-x-y"


def test_title_priority_and_listing_order(tmp_path):
    cfg = setup_config(tmp_path)
    cwd = str(tmp_path / "proj")
    now = time.time()
    write_transcript(cfg, cwd, S1, ["первый вопрос про тесты"], mtime=now - 300)
    write_transcript(cfg, cwd, S2, ["что-то"], custom_title="Починить auth", ai_title="AI title", mtime=now - 60)
    write_transcript(cfg, cwd, S3, ["раз"], ai_title="Сгенерированный", summary="итог", mtime=now - 3600)
    found = sessions.list_sessions(cwd)
    assert [s.session_id for s in found] == [S2, S1, S3]
    assert found[0].title == "Починить auth" and found[0].custom_title == "Починить auth"
    assert found[1].title == "первый вопрос про тесты" and found[1].custom_title is None
    assert found[2].title == "Сгенерированный"
    assert found[0].cwd == cwd
    assert sessions.list_sessions(cwd, limit=1) == found[:1]
    assert sessions.ago(now - 300, now) == "5 мин назад" and sessions.ago(now - 7200, now) == "2 ч назад"


def test_first_prompt_skips_tool_results_meta_and_commands(tmp_path):
    cfg = setup_config(tmp_path)
    cwd = str(tmp_path / "p")
    directory = Path(cfg) / "projects" / sessions.sanitize_cwd(cwd)
    directory.mkdir(parents=True)
    lines = [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}, "cwd": cwd},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/compact</command-name> args"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "  настоящий\nвопрос  "}]}},
    ]
    (directory / f"{S1}.jsonl").write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n")
    (directory / f"{S2}.jsonl").write_text(json.dumps(lines[2]) + "\n")            # only a command
    (directory / f"{S3}.jsonl").write_text(json.dumps({"type": "user", "isMeta": True, "message": {"content": "m"}}) + "\n")
    (directory / "notes.txt").write_text("ignored")
    found = {s.session_id: s for s in sessions.list_sessions(cwd)}
    assert found[S1].title == "настоящий вопрос" and found[S1].cwd == cwd
    assert found[S2].title == "/compact"
    assert S3 not in found          # metadata-only


def test_sidechain_and_long_prompts(tmp_path):
    cfg = setup_config(tmp_path)
    cwd = str(tmp_path / "p")
    write_transcript(cfg, cwd, S1, ["x" * 300])
    write_transcript(cfg, cwd, S2, ["side"], sidechain=True)
    found = sessions.list_sessions(cwd)
    assert [s.session_id for s in found] == [S1]
    assert found[0].title == "x" * 200 + "…"


def test_find_by_id_prefix_and_name_across_projects(tmp_path):
    cfg = setup_config(tmp_path)
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    write_transcript(cfg, a, S1, ["a1"], custom_title="Auth fix")
    write_transcript(cfg, b, S2, ["b1"], custom_title="auth FIX")
    write_transcript(cfg, b, S3, ["b2"])
    assert [s.session_id for s in sessions.find_sessions(S1)] == [S1]
    assert [s.session_id for s in sessions.find_sessions("3333", a)] == [S3]           # other project
    assert sessions.find_sessions("333") == []                                          # prefix too short
    assert sessions.find_sessions("nope") == []
    assert {s.session_id for s in sessions.find_sessions("auth fix")} == {S1, S2}      # ambiguous name
    assert sessions.session_title(S1, a) == "Auth fix" and sessions.session_title(S1, b) is None
