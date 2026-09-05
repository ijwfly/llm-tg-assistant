# llm-tg-assistant

A Telegram bot that drives Claude Code sessions on your server or laptop. One topic in the chat =
one folder and the current `claude` session in it. Write into a topic as you would into a terminal:
text, photos, files, voice notes, forwards. The answer streams as a live draft with progress,
permission requests for commands and edits arrive as cards with buttons, and files come back as
attachments.

Design and decisions live in `specs/PROJECT_SPEC.md` (Russian); how the project is developed is in
`CLAUDE.md`.

## Requirements

- Docker with docker compose (or Python 3.12 and Postgres 16 on the host).
- A Claude account with a subscription (OAuth login from `~/.claude`) or an `ANTHROPIC_API_KEY`.
- A dedicated Telegram bot from @BotFather. In Bot Settings enable **Topics**: the private chat with
  the bot then gets topics, and each topic becomes its own session. Without topics the bot runs a
  single session in the private chat, and per-topic sessions in forum supergroups.
- Your Telegram id (for example from @userinfobot): the bot silently ignores everyone not on the list.

## Quick start (docker compose)

```bash
cp .env.example .env                              # token, ALLOWED_USERS, paths to your projects and ~/.claude
cp settings_local.py.example settings_local.py    # optional overrides
docker compose up -d --build
docker compose logs -f bot
```

`WORK_ROOT` and `CLAUDE_HOME` (usually `~/.claude`) from `.env` are mounted into the container
**at the same absolute paths as on the host**. Claude Code names the transcript folder after the
working directory, so with identical paths a session started in a terminal and one started from the
bot land in the same folder: the «Sessions» list shows both, and `claude --resume <id>` works from
either side. The bot never leaves `WORK_ROOT`; `CLAUDE_HOME` gives the container the transcripts,
the subscription login and `settings.json`. Set `UID/GID` to your own so files edited by Claude Code
stay yours. Paths in `settings_local.py` (`DEFAULT_CWD`, `PROJECTS`, `NEW_PROJECTS_DIR`, `ADD_DIRS`)
are host paths and work unchanged in both modes.

Send `/status` to the bot: the topic card appears. Then just write.

## Running on the host (development)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
docker run -d --name llm-tg-dev-db -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app_dev -p 55433:5432 postgres:16
cp settings_local.py.example settings_local.py   # TELEGRAM_BOT_TOKEN, ALLOWED_USERS, DATABASE_URL=postgresql://app:app@localhost:55433/app_dev, WORK_ROOT, DEFAULT_CWD, INBOX_DIR
.venv/bin/python -m app.main
```

You need `claude` installed (`npm i -g @anthropic-ai/claude-code`) and logged into the subscription.
Tests: `bash scripts/test.sh` (starts its own Postgres in Docker); fully containerized:
`bash scripts/test_docker.sh`.

Without Docker at all (Postgres from Homebrew, `brew services start postgresql@16`): create a role `app`
and databases `app` and `app_test`, put `DATABASE_URL = "postgresql://app:app@localhost:5432/app"` into
`settings_local.py`, and run the tests with `TEST_DATABASE_URL=postgresql://app:app@localhost:5432/app_test
.venv/bin/python -m pytest`. To keep the bot running on a Mac, a launchd agent in
`~/Library/LaunchAgents/` with `ProgramArguments` = `.venv/bin/python -m app.main`, `WorkingDirectory` =
the checkout, `KeepAlive`, `RunAtLoad`, and a `PATH` that includes the directory of `claude` does it:
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`; logs go where `StandardOutPath`
points. Compose is the better fit on a Linux server.

## How to use it

- **Topic = folder.** The first message in a topic starts a session in `DEFAULT_CWD`.
  `/project <alias|path>` opens a topic for an existing folder, `/project new <name>` creates a
  folder, a session and a topic.
- **The topic card** (`/status`) is the control panel: interrupt, retry, new context, stop the process,
  permissions, model, effort, sessions, branch, delete topic; the «More» page holds answer preview,
  thinking line, turn stats, voice answers, tool output, reactions, «Always» rules, file rewind.
- **Sessions.** The «Sessions» button lists every Claude Code session on the machine inside
  `WORK_ROOT`, including ones started in the terminal. «Continue here» attaches a session to the
  current topic (same folder), «New topic» opens a topic for another session's folder. Back to the
  terminal: `claude --resume <id>`. Two writers on one session at the same time is a bad idea: close
  the terminal before continuing in Telegram.
- **Permissions.** The default mode is `auto`: Claude Code's own classifier decides, and what it
  cannot decide comes as a card. `prompt` shows a card for every action Claude Code did not allow by
  itself: «Allow», «Deny», «Always: <rule>» (written to the project's `.claude/settings.local.json`,
  so it applies in the terminal too), «Deny and explain». `acceptEdits` lets edits through, `plan` is
  plan-only with approval, `dontAsk`/`bypass` never ask (`bypass` needs `ALLOW_BYPASS = True`).
  The mode is per topic («Права» on the card); `DEFAULT_PERMISSION_MODE` only seeds new topics.
- **Questions and plans** from the model come as buttons: options, «Own answer», «Execute, edits without
  questions» / «ask about edits» / «Rework the plan».
- **Media.** The model sees photos as images; documents and voice notes are saved to the inbox and
  passed as paths; voice is transcribed through `TRANSCRIBE_CMD`. Forwards and files without a caption
  are staged (👀 reaction) and go along with the next question.
- **Commands** (all in the «/» menu): `/status`, `/new`, `/project`, `/rename`, `/plan`, `/auto`,
  `/files`, `/usage`, `/help`. `/plan` and `/auto` switch the topic's permission mode in one go; the
  other modes are on the card. `/soul [path|off|default]` (per-topic persona) works but is hidden. Any other `/command` (`/compact`, `/cost`, `/context`, skills) goes to Claude Code as is.

The bot speaks Russian in the chat (`app/transport/texts.py` holds every string).

## Settings

Defaults are in `settings.py`; overrides go to `settings_local.py` (gitignored) or, for the basic
keys, environment variables. The useful ones:

| Key | What it does |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `ALLOWED_CHATS`, `NOTIFY_CHAT` | access and start/stop notices |
| `WORK_ROOT`, `DEFAULT_CWD`, `PROJECTS`, `NEW_PROJECTS_DIR` | folders: the boundary, the folder for new topics, aliases, where `/project new` creates folders |
| `DEFAULT_PERMISSION_MODE`, `ALLOW_BYPASS`, `ALLOWED_TOOLS`, `DISALLOWED_TOOLS`, `CLAUDE_SETTINGS`, `ADD_DIRS` | Claude Code permissions |
| `DEFAULT_MODEL`, `DEFAULT_EFFORT`, `MODEL_CHOICES`, `FALLBACK_MODEL`, `MAX_BUDGET_USD_PER_TURN` | model and limits |
| `SOUL_PATH`, `BRIDGE_PREAMBLE_PATH` | persona and the bridge preamble in the system prompt |
| `TRANSCRIBE_CMD`, `TTS_CMD` | voice: speech-to-text (`{file}`, `{wav}`) and text-to-speech (`{text_file}`, `{wav}`, `{out}`) |
| `BRIDGE_SEND_FILE_TOOL`, `VERBOSE_TOOL_OUTPUT`, `FORWARD_SUBAGENT_TEXT`, `FILE_CHECKPOINTING` | files out, tool output, subagents, file rewind |
| `IDLE_TIMEOUT_SECS`, `TURN_TIMEOUT_SECS`, `PERMISSION_TIMEOUT_SECS`, `QUESTION_TIMEOUT_SECS` | timeouts for the process, a turn, the cards |
| `USE_DRAFTS`, `STREAM_PREVIEW`, `THINKING_PREVIEW`, `SHOW_TURN_STATS`, `REACTIONS` | display defaults (switchable on the card) |
| `BRIDGE_SOCKET`, `INBOX_DIR`, `INBOX_TTL_DAYS`, `CLAUDE_CONFIG_DIR`, `CLAUDE_BIN` | paths |

Voice example on macOS: `TTS_CMD = "say -o {wav} --data-format=LEI16@22050 -f {text_file} && ffmpeg -y -loglevel error -i {wav} -c:a libopus {out}"`.
For the container add `ffmpeg`/`whisper` to the image yourself: the base image has neither.

## Operations

- Logs: `docker compose logs -f bot`. Level: `LOG_LEVEL`.
- Restart: `docker compose restart bot`. Running turns get the `⏹` verdict, the «Retry» button
  repeats the turn; the outgoing queue (outbox in Postgres) is delivered after start.
- Migrations `app/store/migrations/*.sql` are idempotent and run at database init and at every bot
  start. Backup: `docker compose exec db pg_dump -U app app > backup.sql`.
- Update: `git pull && docker compose up -d --build` (the Claude Code version is pinned in `Dockerfile`).
- Data: transcripts and the login live in `CLAUDE_HOME`, files from the chat in the `inbox` volume
  (`INBOX_TTL_DAYS`), topic state and the queue in Postgres (`pgdata`).

## Troubleshooting

- The bot stays silent: check that your id is in `ALLOWED_USERS`; strangers get no reply at all.
- The «/» menu shows old commands: Telegram caches the list, reopen the chat.
- A topic created by the bot cannot be deleted from the client: a Telegram limitation; the «Delete
  topic» button on the card does it through the bot.
- A permission card hangs: after `PERMISSION_TIMEOUT_SECS` (10 min) it denies itself; if Claude Code
  cannot see the bridge MCP server, check `BRIDGE_SOCKET` (the socket must be reachable by the `claude` process).
- Inside the container Claude Code keeps its own global state file `CLAUDE_HOME/.claude.json`
  (on the host it is `~/.claude.json`, outside `CLAUDE_HOME`): the subscription login comes from
  `CLAUDE_HOME/.credentials.json` and works, but user-level MCP servers and per-project trust from the
  host file are not shared. Put project MCP servers into the project's `.mcp.json` instead.
- The session does not remember the context after «Continue here»: the session is also open in a
  terminal; close it.
