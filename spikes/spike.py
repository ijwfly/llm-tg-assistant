#!/usr/bin/env python3
"""Phase 0 spike driver: runs real `claude -p` with stream-json and records what happens.

Usage:
    python spikes/spike.py <experiment> [--model haiku] [--out DIR]
    experiments: perm, perm_local, ask, plan, image, sigint, resume, segments, sdk, none, all

Each run writes <out>/<experiment>/{events.jsonl, mcp.log, summary.txt} and prints a summary.
Never commits anything; sandboxes live under --out.
"""
import argparse
import asyncio
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "mcp_spike_server.py"
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")


def clean_env():
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE_CODE") or k in {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"})}
    return env


def mcp_config(log_path: Path, policy_path: Path):
    return json.dumps({"mcpServers": {"tgbridge": {
        "command": sys.executable, "args": [str(SERVER)],
        "env": {"SPIKE_LOG": str(log_path), "SPIKE_POLICY": str(policy_path)},
    }}})


def user_message(content):
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def describe(ev):
    t = ev.get("type")
    if t == "system":
        return f"system/{ev.get('subtype')}"
    if t == "stream_event":
        e = ev.get("event", {})
        d = e.get("delta", {}) or {}
        cb = e.get("content_block", {}) or {}
        tail = d.get("type") or cb.get("type") or ""
        if cb.get("type") == "tool_use":
            tail += f":{cb.get('name')}"
        return f"stream/{e.get('type')}:{tail}"
    if t in ("assistant", "user"):
        blocks = []
        content = ev.get("message", {}).get("content", []) or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content:
            bt = b.get("type")
            if bt == "tool_use":
                blocks.append(f"tool_use:{b.get('name')}")
            elif bt == "text":
                blocks.append(f"text({len(b.get('text',''))})")
            elif bt == "tool_result":
                blocks.append("tool_result" + (":err" if b.get("is_error") else ""))
            else:
                blocks.append(bt or "?")
        p = ev.get("parent_tool_use_id")
        return f"{t}[{','.join(blocks)}]" + (f" parent={p[:8]}" if p else "")
    if t == "result":
        return (f"result/{ev.get('subtype')} err={ev.get('is_error')} turns={ev.get('num_turns')} "
                f"cost={ev.get('total_cost_usd')} denials={len(ev.get('permission_denials') or [])}")
    return t or "?"


class Run:
    def __init__(self, name, out: Path, model: str):
        self.name = name
        self.dir = out / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.sandbox = self.dir / "sandbox"
        self.sandbox.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.sandbox, check=True)
        self.mcp_log = self.dir / "mcp.log"
        self.policy = self.dir / "policy.json"
        self.events_path = self.dir / "events.jsonl"
        self.summary = self.dir / "summary.txt"
        self.model = model
        self.events = []
        self.lines = []

    def note(self, s):
        print(s)
        self.lines.append(s)

    def set_policy(self, policy: dict):
        self.policy.write_text(json.dumps(policy, indent=1))

    def base_args(self, mode="manual", prompt_tool=True, session_id=None, resume=None,
                  verbose=True, partial=True, extra=None):
        args = [CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--replay-user-messages", "--model", self.model, "--permission-mode", mode,
                "--strict-mcp-config", "--mcp-config", mcp_config(self.mcp_log, self.policy)]
        if verbose:
            args.append("--verbose")
        if partial:
            args.append("--include-partial-messages")
        if prompt_tool:
            args += ["--permission-prompt-tool", "mcp__tgbridge__approve"]
        if resume:
            args += ["--resume", resume]
        elif session_id:
            args += ["--session-id", session_id]
        if extra:
            args += extra
        return args

    async def run(self, args, messages, cwd=None, on_event=None, timeout=240, label=""):
        """messages: list of content (str or blocks). Each sent after previous `result`."""
        cwd = cwd or self.sandbox
        self.note(f"\n$ {' '.join(a if len(a) < 60 else a[:57] + '…' for a in args)}")
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, env=clean_env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stderr_chunks = []

        async def read_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                stderr_chunks.append(line.decode(errors="replace"))

        stderr_task = asyncio.create_task(read_stderr())
        pending = list(messages)
        results = []
        started = time.time()

        def send_next():
            if pending:
                m = pending.pop(0)
                proc.stdin.write(user_message(m).encode())

        send_next()
        with open(self.events_path, "a") as ef:
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
                    if not line:
                        break
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        self.note(f"  [non-json stdout] {line[:200]!r}")
                        continue
                    ev["_t"] = round(time.time() - started, 2)
                    ev["_run"] = label
                    self.events.append(ev)
                    ef.write(json.dumps(ev) + "\n")
                    d = describe(ev)
                    if not d.startswith("stream/"):
                        self.note(f"  {ev['_t']:6.2f}s {d}")
                    if on_event:
                        await on_event(proc, ev)
                    if ev.get("type") == "result":
                        results.append(ev)
                        if pending:
                            send_next()
                        else:
                            if not proc.stdin.is_closing():
                                proc.stdin.close()
            except asyncio.TimeoutError:
                self.note(f"  !! timeout after {timeout}s, killing")
                proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        await stderr_task
        err = "".join(stderr_chunks)
        (self.dir / f"stderr{('_' + label) if label else ''}.txt").write_text(err)
        self.note(f"  exit={proc.returncode} stderr={len(err)} chars" + (f": {err.strip()[:300]!r}" if err.strip() else ""))
        return results

    def mcp_calls(self):
        calls = []
        if self.mcp_log.exists():
            for line in self.mcp_log.read_text().splitlines():
                rec = json.loads(line)
                if rec.get("event") == "request" and rec.get("method") == "tools/call":
                    calls.append(rec["params"])
        return calls

    def final_text(self, results):
        return [r.get("result") for r in results]

    def finish(self):
        self.summary.write_text("\n".join(self.lines) + "\n")
        print(f"\n[{self.name}] artifacts in {self.dir}")


# ---------------------------------------------------------------- experiments

async def exp_perm(out, model, destination="session"):
    r = Run("perm" if destination == "session" else "perm_local", out, model)
    r.set_policy({
        "default": {"behavior": "allow"},
        "Bash": {"behavior": "allow", "updatedPermissions": [{
            "type": "addRules", "behavior": "allow", "destination": destination,
            "rules": [{"toolName": "Bash", "ruleContent": "mkdir *"}]}]},
    })
    sid = str(uuid.uuid4())
    results = await r.run(r.base_args(session_id=sid), [
        "Run the shell command `mkdir dir_alpha` using the Bash tool. Then, as a separate Bash tool call, run "
        "`mkdir dir_beta`. Do not use any other tool. Reply `done` when both exist."])
    calls = r.mcp_calls()
    r.note(f"\nprompt-tool calls: {len(calls)}")
    for c in calls:
        r.note("  " + json.dumps(c, ensure_ascii=False)[:1500])
    r.note(f"final: {r.final_text(results)}")
    local = r.sandbox / ".claude" / "settings.local.json"
    r.note(f"settings.local.json exists: {local.exists()}" + (f" -> {local.read_text()}" if local.exists() else ""))
    r.note(f"session dir: {sandbox_project_dir(r.sandbox)}")
    r.finish()


async def exp_ask(out, model):
    r = Run("ask", out, model)
    r.set_policy({"default": {"behavior": "allow"}, "AskUserQuestion": {"behavior": "allow", "answer_index": 1}})
    results = await r.run(r.base_args(session_id=str(uuid.uuid4())), [
        "Use the AskUserQuestion tool to ask me which colour I prefer, with exactly two options: Red and Blue. "
        "After I answer, reply with only the colour I picked."])
    for c in r.mcp_calls():
        r.note("  call: " + json.dumps(c, ensure_ascii=False)[:2000])
    r.note(f"final: {r.final_text(results)}")
    r.finish()


async def exp_plan(out, model):
    r = Run("plan", out, model)
    r.set_policy({
        "default": {"behavior": "allow"},
        "ExitPlanMode": {"behavior": "allow", "updatedPermissions": [
            {"type": "setMode", "mode": "acceptEdits", "destination": "session"}]},
    })
    sid = str(uuid.uuid4())
    results = await r.run(r.base_args(mode="plan", session_id=sid), [
        "Plan how to create a file named hello.txt in the current directory containing the single line `hi`. "
        "Write the plan, then call ExitPlanMode. Once the plan is approved, create the file with the Write tool "
        "and reply `done`."], timeout=300)
    for c in r.mcp_calls():
        r.note("  call: " + json.dumps(c, ensure_ascii=False)[:2500])
    r.note(f"final: {r.final_text(results)}")
    r.note(f"hello.txt exists: {(r.sandbox / 'hello.txt').exists()}")
    r.finish()


def red_png(size=64):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


async def exp_image(out, model):
    import base64
    r = Run("image", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    data = base64.b64encode(red_png()).decode()
    results = await r.run(r.base_args(session_id=str(uuid.uuid4())), [[
        {"type": "text", "text": "What is the dominant colour of this image? Answer with one word."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
    ]])
    r.note(f"final: {r.final_text(results)}")
    r.finish()


async def exp_sigint(out, model):
    r = Run("sigint", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    state = {"sent": False}

    async def on_event(proc, ev):
        if state["sent"]:
            return
        if ev.get("type") == "assistant":
            for b in ev.get("message", {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                    await asyncio.sleep(2)
                    r.note(f"  >> sending SIGINT (pid {proc.pid})")
                    proc.send_signal(signal.SIGINT)
                    state["sent"] = True

    results = await r.run(r.base_args(session_id=str(uuid.uuid4())), [
        "Run `sleep 40` with the Bash tool, then reply `slept`.",
        "Reply with the single word `pong`."], on_event=on_event, timeout=120)
    r.note(f"results: {[(x.get('subtype'), x.get('result')) for x in results]}")
    r.finish()


def sandbox_project_dir(path: Path):
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    enc = "".join(ch if ch.isalnum() else "-" for ch in str(path))
    d = cfg / "projects" / enc
    files = sorted(d.glob("*.jsonl")) if d.exists() else []
    return f"{d} ({len(files)} transcripts)"


async def exp_resume(out, model):
    r = Run("resume", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    sid = str(uuid.uuid4())
    other = r.dir / "other_cwd"
    other.mkdir()
    await r.run(r.base_args(session_id=sid), ["The codeword is ZEBRA. Acknowledge with `ok`."], label="a")
    r.note(f"transcripts for sandbox: {sandbox_project_dir(r.sandbox)}")
    results = await r.run(r.base_args(resume=sid), ["What is the codeword? One word."], cwd=other, label="b")
    r.note(f"final from other cwd: {r.final_text(results)}")
    init = [e for e in r.events if e.get("type") == "system" and e.get("subtype") == "init" and e.get("_run") == "b"]
    if init:
        r.note(f"init(b): session_id={init[0].get('session_id')} cwd={init[0].get('cwd')}")
    r.note(f"transcripts for other cwd: {sandbox_project_dir(other)}")
    results = await r.run(r.base_args(resume=sid, extra=["--fork-session", "--name", "spike-fork"]),
                          ["Codeword again, one word."], cwd=other, label="c")
    init = [e for e in r.events if e.get("type") == "system" and e.get("subtype") == "init" and e.get("_run") == "c"]
    r.note(f"fork: final={r.final_text(results)} init.session_id={init[0].get('session_id') if init else None} (orig {sid})")
    r.finish()


async def exp_segments(out, model):
    r = Run("segments", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    prompt = ("Say the sentence `First part is here.` Then run `echo mid` with the Bash tool. "
              "Then say the sentence `Second part is here.` Nothing else.")
    await r.run(r.base_args(session_id=str(uuid.uuid4())), [prompt], label="verbose")
    stream_types = [describe(e) for e in r.events if e.get("type") == "stream_event"]
    r.note(f"verbose: {len(stream_types)} stream events; kinds: {sorted(set(stream_types))}")
    n_before = len(r.events)
    await r.run(r.base_args(session_id=str(uuid.uuid4()), verbose=False), [prompt], label="noverbose")
    tail = r.events[n_before:]
    r.note(f"no --verbose: {len([e for e in tail if e.get('type')=='stream_event'])} stream events, "
           f"{len([e for e in tail if e.get('type')=='assistant'])} assistant msgs")
    r.note("full event order (verbose run):")
    for e in r.events[:n_before]:
        r.note(f"   {e['_t']:6.2f}s {describe(e)}")
    r.finish()


async def exp_none(out, model):
    r = Run("none", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    prompt = "Run `mkdir dir_alpha` with the Bash tool and reply `done`."
    res = await r.run(r.base_args(prompt_tool=False, extra=["--permission-prompts", "none"]), [prompt], label="none")
    r.note(f"--permission-prompts none: {[(x.get('subtype'), x.get('permission_denials'), x.get('result')) for x in res]}")
    res = await r.run(r.base_args(mode="dontAsk", prompt_tool=False), [prompt], label="dontask")
    r.note(f"dontAsk: {[(x.get('subtype'), x.get('permission_denials'), x.get('result')) for x in res]}")
    r.finish()


def exp_sdk(out, model):
    r = Run("sdk", out, model)
    venv = out / "venv"
    if not (venv / "bin" / "python").exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run([str(venv / "bin" / "pip"), "install", "-q", "claude-agent-sdk"], check=True)
    resume_sandbox = out / "resume" / "sandbox"
    code = f"""
import json, claude_agent_sdk as s
print("sdk version", getattr(s, "__version__", "?"))
from claude_agent_sdk import list_sessions
for d in [{str(resume_sandbox)!r}, {str(Path.cwd())!r}]:
    try:
        ss = list_sessions(directory=d, limit=5)
        print("dir", d, "->", len(ss))
        for x in ss:
            print("  ", x.session_id[:8], x.summary[:60] if x.summary else None, x.custom_title, x.cwd, x.last_modified)
    except Exception as e:
        print("dir", d, "ERROR", type(e).__name__, e)
"""
    p = subprocess.run([str(venv / "bin" / "python"), "-c", code], capture_output=True, text=True, env=clean_env())
    r.note(p.stdout + p.stderr)
    r.finish()


async def exp_deny(out, model):
    r = Run("deny", out, model)
    r.set_policy({"default": {"behavior": "allow"},
                  "Bash": {"behavior": "deny", "message": "User says: do not create directories, create a file notes.txt instead"}})
    results = await r.run(r.base_args(session_id=str(uuid.uuid4())), [
        "Run `mkdir dir_alpha` with the Bash tool. If that is not allowed, do what the user asks instead and reply `done`."])
    for e in r.events:
        if e.get("type") == "user":
            for b in e.get("message", {}).get("content", []) or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    r.note("  tool_result: " + json.dumps(b, ensure_ascii=False)[:600])
        if e.get("type") == "system" and e.get("subtype") not in ("init", "status", "thinking_tokens"):
            r.note("  system: " + json.dumps(e, ensure_ascii=False)[:600])
    r.note(f"final: {r.final_text(results)}; notes.txt exists: {(r.sandbox / 'notes.txt').exists()}")
    r.finish()


async def exp_sigint_resume(out, model):
    sid = None
    src = out / "sigint" / "events.jsonl"
    for line in src.read_text().splitlines():
        e = json.loads(line)
        if e.get("type") == "system" and e.get("subtype") == "init":
            sid = e["session_id"]
    r = Run("sigint_resume", out, model)
    r.set_policy({"default": {"behavior": "allow"}})
    for line in src.read_text().splitlines():
        e = json.loads(line)
        if e.get("type") == "user":
            c = e.get("message", {}).get("content")
            if isinstance(c, str) or (isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "text"):
                r.note("  user text in sigint run: " + json.dumps(c, ensure_ascii=False)[:200])
    results = await r.run(r.base_args(resume=sid), ["What did I ask you to run before? One line."])
    r.note(f"final: {r.final_text(results)}")
    r.finish()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--out", default=os.environ.get("SPIKE_OUT", "/tmp/spike_out"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    table = {
        "perm": lambda: exp_perm(out, a.model),
        "perm_local": lambda: exp_perm(out, a.model, "localSettings"),
        "ask": lambda: exp_ask(out, a.model),
        "plan": lambda: exp_plan(out, a.model),
        "image": lambda: exp_image(out, a.model),
        "sigint": lambda: exp_sigint(out, a.model),
        "resume": lambda: exp_resume(out, a.model),
        "segments": lambda: exp_segments(out, a.model),
        "none": lambda: exp_none(out, a.model),
        "deny": lambda: exp_deny(out, a.model),
        "sigint_resume": lambda: exp_sigint_resume(out, a.model),
    }
    names = list(table) if a.experiment == "all" else [a.experiment]
    for n in names:
        if n == "sdk":
            exp_sdk(out, a.model)
            continue
        await table[n]()
    if a.experiment in ("all", "sdk"):
        exp_sdk(out, a.model)


if __name__ == "__main__":
    asyncio.run(main())
