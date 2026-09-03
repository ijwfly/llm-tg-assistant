# CLAUDE.md — project map and development workflow

This file is the map of the project (§0) and defines how work is done in this repository: the development loop, testing, git, specs, documentation, configuration and deployment. Follow it for every change, big or small.

## 0. Project map

**What**: a Telegram bot that drives Claude Code sessions on a server with a native chat UX —
one forum topic (or private-chat topic) = one Claude Code session. Design: `specs/PROJECT_SPEC.md`
(read its status line first); phase specs `specs/PHASE_*.md`; tests `specs/E2E_TESTS.md`.

**Run**: `cp .env.example .env`, `cp settings_local.py.example settings_local.py`, fill the
token and `ALLOWED_USERS`, then `docker compose up -d --build`. Locally: `.venv/bin/python -m app.main`.
**Test**: `bash scripts/test.sh [-k name -v]` (needs Docker for the test Postgres).

**Layout** (Python 3.12, aiogram 3.31, asyncpg, Postgres 16):

| Path | Concern |
|---|---|
| `settings.py` / `settings_local.py` | defaults (env-var backed) / secrets and overrides, gitignored |
| `app/main.py` | entry point: validate settings, connect DB, migrate, polling |
| `app/app.py` | `App`: wires store, sender, outbox worker, topics, dispatcher; start/stop notices |
| `app/store/db.py`, `repos.py`, `migrations/` | asyncpg pool, idempotent `NNNN_*.sql` migrations (applied by the DB container init **and** at app start), repositories |
| `app/transport/bot.py` | dispatcher wiring, `ALLOWED_UPDATES`, command menu |
| `app/transport/middleware.py` | `AccessMiddleware` (ALLOWED_USERS/ALLOWED_CHATS, silent), `DedupMiddleware` (update_id, marked before handling) |
| `app/transport/handlers.py` | commands and messages; `build_router()` per dispatcher; `topic_ref()` maps a message to `(chat_id, thread_id)` |
| `app/transport/sender.py`, `outbox.py` | the only door for outgoing calls: rows in `outbox`, worker delivers per-topic in order, parallel across topics, 429/backoff/failed |
| `app/transport/texts.py` | every user-facing string (Russian) |
| `app/core/topics.py` | `TopicRef`, `TopicService` |
| `app/core/runtime.py` | `TopicRuntime` (queue, worker task, claude process, idle timer, turn loop, verdicts), `RuntimeRegistry` |
| `app/bridge/cli.py`, `process.py`, `events.py` | argv/env builder (permission-mode map, prompt tool + inline `--mcp-config`, secret stripping), `ClaudeProcess` (spawn, stdin, events, SIGINT, graceful stop), typed stream-json events |
| `app/bridge/mcp_server.py`, `socket_server.py`, `rules.py` | stdlib-only stdio MCP server (`approve`) launched by `claude`, forwards to the daemon's unix socket (`BRIDGE_SOCKET`); `BridgeSocket` server; «Всегда» rule matrix, `updatedPermissions`, forgetting rules in `.claude/settings.local.json` |
| `app/core/prompts.py` | `PromptService`: pending permission/question/plan prompts, cards, buttons, awaited text, timeouts, abandon on cancel; token → runtime registry |
| `app/render/markdown.py`, `progress.py`, `keyboards.py`, `cards.py` | fence-aware splitter and preview rules; progress line, tool trail, draft/progress content; inline keyboards and `callback_data` codec; permission (diff/masking), question and plan cards |
| `app/core/liveview.py` | `LiveView`: draft (private) or progress message (groups), trailing-edge gate, 429, keepalive, delete after finals |
| `app/core/actions.py` | topic actions shared by commands and buttons (new, stop, cancel, retry, continue, perm, perm forget, card) |
| `app/transport/callbacks.py` | inline-button dispatcher → `actions`; stale buttons answer a toast |
| `app/ingest/batcher.py`, `classify.py`, `pipeline.py`, `files.py`, `transcribe.py` | sliding-window batcher per topic; prompt/staging matrix, forward attribution, file-name sanitizing; turn assembly (downloads, image blocks, staging consumption, reply quote); inbox with TTL cleanup; external STT command |
| `spikes/` | phase-0 experiment scripts against the real `claude` (documentation, not product code) |
| `tests/` | e2e (real dispatcher + real Postgres + recording Telegram session), unit, `fake_claude/` |

**Request flow**: Telegram update → `AccessMiddleware` → `DedupMiddleware` → router handler →
`TopicService` → `Batcher` (300 ms window) → `Ingest.process_batch` (staging or turn) → `TopicRuntime.submit` → `ClaudeProcess` stdin → stream-json events → `LiveView` (drafts /
progress edits, direct, ephemeral) and `TelegramSender.enqueue` → `outbox` table → `OutboxWorker` → Bot API
(rich → plain fallback, `file://` → `FSInputFile`) → `message_links`. Buttons: callback → `callbacks.py` → `actions` / `prompts`.
**Prompt flow**: `claude` calls `mcp__tgbridge__approve` → `mcp_server.py` → unix socket → `PromptService.handle` (token → runtime) → card via outbox → button / next text message / timeout → decision JSON back → `claude`.

**Key patterns**: read `settings.X` at call time (tests override the module); never call the
Bot API directly from handlers — enqueue through `TelegramSender`; strings live in `texts.py`;
a message belongs to a topic only when `is_topic_message` is set; the claude process is only touched under
`TopicRuntime._lock`; a turn ends only on a `result` event (EOF without it = crash → one silent retry);
buttons first, slash commands as the text fallback — every action lives in `core/actions.py` and is reachable
from both; live-view updates bypass the outbox (ephemeral), everything the user keeps goes through it; outbox payloads
are produced by `sender.dump_method` (drops aiogram `Default` sentinels, keeps discriminators); `mcp_server.py` must stay
stdlib-only (it runs from the topic's cwd under the daemon's interpreter and never imports the app); a pending prompt is
resolved exactly once (`PendingPrompt.future`), and every path that ends a turn calls `prompts.abandon`.

**Claude Code facts that shape the code** (verified in phase 0): `claude -p` needs `--verbose`
with stream-json; assistant events arrive one content block at a time; SIGINT ends the turn and
the process; the permission prompt tool receives `{tool_name, input, tool_use_id}` and answers
with `{"behavior": ...}` JSON; `updatedPermissions` with `localSettings` writes
`.claude/settings.local.json`.

## 1. Development cycle

Every task goes through the same loop:

1. **Understand the task.** Read the relevant code and the existing specs in `specs/` before proposing anything. Reuse existing helpers and patterns; do not add a second way of doing something that already has one.
2. **Spec first for anything non-trivial.** A multi-step change (new feature, migration, refactor touching several modules) gets a spec in `specs/` with phases before any code is written (§4). Small fixes do not need a spec.
3. **Branch.** Never work on `main`. Create `claude/<topic>` from `main`, or from the currently open feature branch when the new work depends on it (§3).
4. **Implement in phases.** Keep each phase small enough to review and to attribute a test failure to. After **any** code change run the full test suite (§2) and fix failures before moving on.
5. **Update documentation in the same phase**: the spec's status line and phase table, the affected section of `CLAUDE.md`, and the `CHANGELOG.md` entry (§5).
6. **Commit per phase with tests green, push the branch, open a PR** (§3). The user merges; do not merge yourself.
7. **Report faithfully**: what was done, what was verified and how, what was skipped and why. If tests were not run, say so.

## 2. Testing

### Running

- The single entry point is `bash scripts/test.sh`. It starts the test database container if it is not already running, waits for it to become healthy, runs the whole suite, and tears the container down on exit (via a shell `trap`, so teardown also happens on failure). Extra arguments are forwarded to the test runner, so `bash scripts/test.sh -k reply -v` works.
- A fully containerized variant (`scripts/test_docker.sh`) builds the app image and runs the same suite inside compose; use it for CI or when the host environment is suspect.
- **All tests must pass before work is considered done.** Never commit on red. Never skip, weaken or delete a test to make it pass. A test that fails after your change is your bug until proven otherwise.

### Philosophy

- **End-to-end first.** Tests drive the application through the framework's public entry point (feed a synthetic update/request into the real dispatcher) and assert on the observable outcome. The real handler pipeline, middleware, persistence and response path all execute.
- **Real database, mocked edges.** The database runs in a container with the real migrations applied. External APIs (LLM providers, third-party HTTP) and the transport (the messaging platform) are mocked at boundaries that already exist in the code.
- **Zero production changes for testability.** No `if TESTING` branches, no test-only seams, no dependency-injection scaffolding added for tests. If a component cannot be mocked at an existing boundary, that is a design smell to fix in the design, not by leaking test hooks into production code.
- **Unit tests only where e2e cannot reach**: code that runs in another container or process, pure helpers with many edge cases (splitters, parsers). Keep them dependency-free and put them under `tests/unit/`; the rest lives in `tests/e2e/`.

### Mocks and fixtures

- **External API mock** = a FIFO queue of canned responses plus a log of every call made. Tests enqueue responses in arrange, then assert on both the outcome and on what the mock was asked. An exhausted queue raises; that is the error-path test.
- **Transport mock** = a recording session that captures every outgoing request `(method, payload)` and returns the framework's own parsed objects, so handlers behave exactly as in production. Provide `fail_next(method, exception)` to inject a failure into the next call of one method for fallback tests.
- **Build mocks from the vendor SDK's own types**, not hand-written dicts, so an SDK upgrade that changes response shapes fails in tests instead of in production.
- **Spy for assertions** on top of the transport mock, exposing what the user saw in domain terms (`get_sent_messages()`, `get_edited_messages()`, `assert_shown_text_contains(...)`) and hiding representation differences (plain vs formatted vs edited). Assert on what the user saw and on database state, not on which API method delivered it.
- **Settings for tests** are overridden by assigning to the settings module at the top of the root `conftest.py`, before the application is imported; memoized config readers are cache-cleared right after. Optional integrations are disabled through settings, not patched out.
- **Isolation**: an autouse fixture truncates every table after each test in FK-safe order; fixture teardown resets class-level registries and caches; a subdirectory `conftest.py` overrides the autouse DB fixture for unit tests so they touch no database.
- **Timing**: debounce and throttle intervals are patched to near-zero in the app fixture; tests settle with short sleeps (0.05–0.3 s) after feeding an update; long-running turns are bounded with `wait_for(..., timeout=...)` so a hang fails fast; when a test needs a slow stream (to cancel mid-way), drive the timing from the mock's per-chunk delay, not from sleeps in the test. Assert on content boundaries ("first chunk present, last chunk absent"), not on exact counts, wherever timing is involved.
- Async mode is automatic (`asyncio_mode = auto`) with a session-scoped loop; no per-test async markers.

### Writing tests

- **One behaviour per test.** Duplicate the arrange block rather than bundling several assertions into one test. Name tests as sentences describing the behaviour: `test_expired_session_starts_a_fresh_context`, `test_rate_limit_on_a_partial_update_does_not_break_the_request`.
- New behaviour ships with its e2e test in the same commit. A bug fix starts with the failing test that reproduces it.
- Where an unhandled event must be a failure rather than a warning, turn the framework's `RuntimeWarning` into an error for the duration of that test.
- Keep a tests spec (`specs/E2E_TESTS.md` or similar) describing the infrastructure, the pipeline each test file covers, and a **"Not yet covered"** table with a reason and priority per gap. Every feature spec lists the tests its phases must add.

## 3. Git: branches, commits, pushes, pull requests

### Branches

- **Never push to `main`**, even when the request is a bare "push". Every change goes through a feature branch and a pull request; the user merges.
- Branch naming: `claude/<topic>`. Branch from `main` by default.
- **Stacked branches**: if an earlier feature PR is still open and the new work builds on it, branch from that feature branch and open the PR with `--base <that branch>`. Check `gh pr list` before creating a branch. Do not rebase a stacked branch onto `main` unless asked.
- One branch per spec; phases run sequentially on that branch. Follow-ups after review go into the same branch until it is merged.

### Commits

- **One commit per phase, tests green at every commit.** Never combine two unrelated kinds of change (for example a framework migration and an SDK upgrade) in one commit; a failure must be attributable to one change.
- Commit only when asked or when the workflow (a finished phase) calls for it. Before committing run `git status` and make sure no local overrides, secrets, scratch files or generated artifacts are staged.
- Message format:
  - subject: imperative, states the outcome, about 70 characters (`Fix cancellation delivery and rate-limit handling in streaming`; for phased work `<Topic> phase N: <what>`);
  - body: bullets, one per component, saying what changed and why; a final `Tests:` bullet listing the scenarios added or changed;
  - trailers required by the environment (`Co-Authored-By`, session links) at the end, verbatim.

### Pushing

- `git push -u origin <branch>`.
- If SSH is not usable from the session, push over HTTPS with the `gh` credential helper and without touching the user's git config:
  ```
  git -c credential.helper='!gh auth git-credential' push https://github.com/<owner>/<repo>.git HEAD:<branch>
  ```
- Never search keychains, `.netrc` or environment files for credentials. If the token lacks permissions (403), ask the user to widen it instead of retrying.

### Pull requests

- Create with `gh pr create --base <main or stacked branch>`. Title = the feature's commit subject.
- Body template:
  1. `Stacked on #N (<branch>)` as the first line when stacked.
  2. `## Problems` — numbered list: what was wrong or what is needed, with the concrete cause.
  3. `## Changes` — bullets per component; mention behaviour changes, new flags and defaults, tests and docs explicitly.
  4. `## Verification` — the test command and its result, plus a manual smoke list for things tests cannot cover (real transport, real provider).
  5. The footer required by the environment.
- Do not merge. After the PR is open, further changes go into the same branch; keep the PR description current when scope changes.

## 4. Specs as phase checklists

- Any multi-step change gets `specs/<TOPIC>.md` **before** code. The spec is the executable checklist for the work, not an after-the-fact description.
- Structure:
  1. **Status line** at the top: `Status: phase N of M — <one line>`; when done: `Status: all phases done — <summary>; tests green`. Update it at the end of every phase.
  2. **Why** — the problem and the intended outcome.
  3. **Verified facts** — what was checked against documentation, SDK sources or experiments, with caveats. Distinguish "verified" from "assumed".
  4. **Decisions** — a table `question → decision`, so choices are not re-litigated later.
  5. **Design** — the target structure, per module.
  6. **Phases** — a table `# | Phase | Status` with ✅ / ⏳; each phase names its deliverables and the tests it must add.
  7. **Phase results** — a short note appended after each phase: what actually landed, what deviated from the plan.
  8. **Manual smoke checklist** — what to verify by hand after deploy.
  9. **Open questions**.
- Rules: phases run strictly in order on one branch; each phase ends with a green test run and its own commit; the spec is updated **in the same commit** as the code it describes; the last phase is always documentation (`CLAUDE.md`, architecture specs, tests spec, `CHANGELOG.md`) plus the PR.
- When resuming work, read the status line first and continue from the first phase that is not ✅.
- Keep architecture specs current (`specs/PROJECT_SPEC.md` for the whole system, `specs/<LAYER>_ARCHITECTURE.md` for a layer with its own extension points). When an integration is optional, its spec ends with a **Removal recipe**: the exact files and call sites to delete, and a test asserting the dependency is never imported when the feature is disabled.

## 5. Changelog and documentation

- `CHANGELOG.md` follows Keep a Changelog: `## [Unreleased]` with `### Added`, `### Changed`, `### Fixed`, `### Removed`; one bullet per user-visible change, starting with a bold short name, ending with a pointer to the spec for design details. Write the entry in the docs phase of the work, not at release time.
- `CLAUDE.md` is the map, not the manual: what the project is, how to run it, the request flow, key patterns, where each concern lives, the testing rule, library notes. Update the relevant section whenever a module, flag, pattern or command appears or disappears. Keep it scannable; long explanations go to `specs/`.
- `README.md` is for humans setting the project up: quick start, full setup, configuration overrides, operations. Specs are for design. `CLAUDE.md` is for how work is done.
- Never document secret values; refer to settings by name.

## 6. Configuration and secrets

- Defaults live in a committed `settings.py`. **All secrets and machine-specific values** live in a gitignored `settings_local.py`, imported at the very end of `settings.py`:
  ```python
  try:
      from settings_local import *
  except ImportError:
      pass
  ```
- Ship `settings_local.py.example` with every override commented out and grouped (Required / Optional API keys / Database / Features), so a new environment is a copy-and-fill.
- Derived flags (for example "tracing is enabled when both keys are present") are computed **after** the local import and only if the flag was not set explicitly in the local file.
- New risky or expensive behaviour goes behind a setting that is **off by default**, documented in a comment next to the setting and in `CLAUDE.md`.
- Never commit tokens. Never print secret values in output, logs or documents. `.env` and `settings_local.py` are gitignored; `.env.example` and `settings_local.py.example` are committed.
- Database schema changes are numbered, idempotent SQL migrations (`NNNN_short_description.sql`, using `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`) applied automatically when the database container initializes. Never edit a shipped migration; add a new one.
- Dependencies are pinned with `==` and list direct dependencies only. Upgrades are a spec with phases: one dependency family per phase, tests green per phase.

## 7. Deployment with docker-compose

- `docker-compose.yml` is production-shaped and committed: all services, named volumes, migrations mounted into the database init directory, environment via `${VAR:-default}` with a committed `.env.example`.
- Development customizations live **only** in the gitignored `docker-compose.override.yml`, which compose merges automatically. Ship `docker-compose.override.yml.example` with the usual overrides: replace the app entrypoint with a sleep loop so you can exec into the container and run the app manually, publish the database port, add a database web UI. Never commit an override file.
- `docker-compose.test.yml` defines the test database (healthcheck, a host port that does not clash with the dev database) and a containerized test runner; `scripts/test.sh` and `scripts/test_docker.sh` use it.
- Commands:
  - `docker-compose up -d` — start; `docker-compose up -d --build` — after dependency, Dockerfile or image-level changes;
  - `docker-compose logs -f <service>` — follow logs;
  - rebuild the image whenever `requirements` change.
- After a deploy, run the manual smoke checklist from the relevant spec and report the result.

## 8. Working style

- Say in one line what you are about to do, do it, then report what was verified. If a step was skipped, say so; if tests failed, show the output.
- Ask a question only when different readings of the task lead to materially different work; otherwise choose the reasonable option, state the assumption, and proceed.
- Do not widen the scope: no unrelated cleanups in a feature branch. Note rough edges you find as TODOs or in the spec's open questions instead of fixing them silently.
- Prefer existing helpers and patterns over new abstractions; when a pattern must change, change it in one place and update the docs that describe it.
