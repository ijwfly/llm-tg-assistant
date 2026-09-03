# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
- **Test infrastructure** — `scripts/test.sh` with a disposable Postgres, recording Telegram
  session with failure injection, spy, update builders, fake `claude` for the coming phases.
  See `specs/E2E_TESTS.md`.
