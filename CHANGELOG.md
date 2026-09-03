# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- **Outbox stall on permanent Telegram errors** — an in-place card edit with identical content
  (`message is not modified`) was retried forever and, being the head of the topic queue, blocked
  every later message of that topic. Identical edits now count as delivered; other `Bad Request`
  and `Forbidden` errors mark the row `failed` immediately (found on the phase-3 live check).

### Added

- **Project spec** — `specs/PROJECT_SPEC.md`: topic = Claude Code session, raw `claude -p`
  stream-json bridge, rich-markdown streaming, permission/question/plan cards, staging inbox,
  outbox delivery, 9-phase roadmap. Facts verified against real `claude` 2.1.259
  (`specs/PHASE_0_SPIKE.md`, `spikes/`).
- **Skeleton (phase 1)** — settings with `settings_local.py` overrides and env defaults,
  Postgres store with idempotent SQL migrations applied at startup, aiogram 3.31 bot with
  `ALLOWED_USERS`/`ALLOWED_CHATS` locks and `update_id` deduplication, outbox worker with
  at-least-once delivery ordered per topic and 429-aware retries, `/help`, `/whoami`,
  `/topics`, `/status`, startup/shutdown notices to `NOTIFY_CHAT`, docker-compose
  (bot + Postgres) with dev override example. See `specs/PHASE_1_SKELETON.md`.
- **Turns (phase 2)** — a message in a topic is a Claude Code turn: one long-lived
  `claude -p` stream-json process per topic, resumed after idle/stop/cancel, answers delivered
  as rich markdown (plain fallback), end-of-turn verdicts (`✔️`, `⚠️`, `🔒`, `🧹`, `⏹`), cancel via
  SIGINT, turn timeout, silent retry on crash, `/new`, `/clear`, `/stop`, `/cancel`, `/retry`,
  `/cd`, `/go`, extended `/status`, reply quoting, per-topic turn queue with a single hint.
  See `specs/PHASE_2_TURNS.md`.
- **Live view and buttons (phase 3)** — rich drafts with `<tg-thinking>` (progress line, tool
  trail, thinking tail, held-back last word) and native Stop in private chats; editable progress
  message with `🛑` in groups; trailing-edge gate with 429 handling; fence-aware splitter; very
  long answers as a file; short text segments merged; inline buttons on verdicts (`🔁`, `🔓`,
  `▶️`), topic card `/status` with `🆕 ⏸ 🔄 ✖` and in-place redraw, shared actions for commands and
  buttons, `/perm`, command menu reduced to `status`/`new`/`help`. See `specs/PHASE_3_STREAMING.md`.
- **Input pipeline (phase 4)** — sliding-window batcher (album, forwards, text+photo+voice =
  one turn), prompt/staging matrix (forwards and captionless files wait for the next question,
  acknowledged with a 👀 reaction), photos as image blocks plus inbox copies, documents in the
  inbox with paths, voice via `TRANSCRIBE_CMD` with a 🎤 echo, edited messages as new turns,
  `/files`, inbox TTL cleanup, per-user `forward_as_prompt` / `voice_as_prompt` settings.
  See `specs/PHASE_4_INGEST.md`.
- **Permissions, questions and plans (phase 5)** — the bridge is Claude Code's permission
  prompt tool: a stdlib MCP server (`app/bridge/mcp_server.py`) forwards every request over a
  unix socket to the daemon, which shows a card (`Bash` command, `Edit`/`Write` diff, masked
  JSON for other tools) with `✅ ❌ 🔓 Всегда ✏️` buttons; «Всегда» writes an allow rule to the
  project's `.claude/settings.local.json` via `updatedPermissions` and `/perm forget` removes
  it; «Отклонить и объяснить» uses the next message as the reason; unanswered cards time out
  into a deny; `AskUserQuestion` becomes cards with option buttons (multiSelect toggles,
  custom answer); `ExitPlanMode` becomes a plan card with «Выполнять (правки без вопросов)» /
  «спрашивать про правки» / «Доработать»; the live view shows `🔐 жду разрешения`. Settings:
  `BRIDGE_SOCKET`, `PERMISSION_TIMEOUT_SECS`, `QUESTION_TIMEOUT_SECS`, `PERMISSION_DIFF_LINES`.
  See `specs/PHASE_5_PERMISSIONS.md`.
- **Test infrastructure** — `scripts/test.sh` with a disposable Postgres, recording Telegram
  session with failure injection, spy, update builders, fake `claude` for the coming phases.
  See `specs/E2E_TESTS.md`.
