# PHASE_1_SKELETON — скелет приложения и тестовая инфраструктура

Status: all phases done — скелет, outbox, тестовая инфраструктура; tests green (20 passed)

## Why

До ходов Claude Code нужен каркас, на который лягут все следующие фазы: настройки, БД с
миграциями, aiogram-бот с контролем доступа и дедупликацией, outbox с гарантией доставки,
docker-compose и, главное, e2e-инфраструктура (записывающая Telegram-сессия, реальный Postgres,
fake `claude`), чтобы каждая следующая фаза начиналась с теста.

## Verified facts

- aiogram 3.31.0 = Bot API 10.3: `SendRichMessage(chat_id, rich_message: InputRichMessage
  {markdown|html|blocks, media}, message_thread_id, reply_parameters, reply_markup)`,
  `SendRichMessageDraft(chat_id, draft_id, rich_message, message_thread_id, can_stop,
  keep_on_stop) -> bool`, `Update.stopped_message_generation`, тип `MessageGenerationStopped`.
- `BaseSession.make_request(self, bot, method, timeout)`; у каждого метода есть
  `__returning__` (тип результата) и `__api_method__` — на них строится recording-сессия.
- asyncpg 0.31.0; `jsonb` требует codec (`set_type_codec`) либо явного `::jsonb` и `json.dumps`.
- Docker Desktop с compose v5 на машине разработки запущен.

## Decisions

| Вопрос | Решение |
|---|---|
| Миграции | Идемпотентные `app/store/migrations/NNNN_*.sql`; монтируются в init-директорию Postgres **и** применяются приложением при старте (двойное применение безопасно) — так новые миграции доезжают на существующий volume. |
| Outbox | Одна таблица `outbox`; воркер берёт по одной pending-строке на `topic_key` (`DISTINCT ON`), доставляет параллельно между темами и строго по порядку внутри темы. `TelegramRetryAfter` → `next_attempt_at = now + retry_after` только для этой темы; прочие ошибки → экспоненциальный backoff (`OUTBOX_RETRY_BASE_SECS`), старше `OUTBOX_MAX_AGE_SECS` → `failed`. Метод хранится по имени класса aiogram (`SendMessage`) + `payload` = `model_dump(mode="json")`, восстанавливается `model_validate`. |
| Доступ | Outer-middleware на `Update`: чужой пользователь — молча (callback → тост «Not authorized»); `ALLOWED_CHATS` — вторым замком. Дедуп `update_id` — второй middleware, помечает **до** обработки. |
| Тема | `(chat_id, thread_id)`; `thread_id` берётся только при `is_topic_message`, иначе NULL (reply-треды в обычных группах — не темы). Уникальный индекс по `(chat_id, COALESCE(thread_id, 0))`. |
| Секреты | `settings.py` читает переменные окружения как значения по умолчанию (для compose), `settings_local.py` — поверх. |
| Команды фазы | `/help` (`/start` = `/help`), `/whoami`, `/topics`, `/status` (без полей процесса). Любое другое сообщение создаёт тему и отвечает заглушкой `🚧 …` — заменится в фазе 2. |
| fake `claude` | `tests/fake_claude/claude` — Python-скрипт: разбирает `--session-id/--resume/--mcp-config`, пишет argv и каждую stdin-строку в `FAKE_CLAUDE_LOG`, на каждый user-message воспроизводит следующий сценарий из `FAKE_CLAUDE_SCENARIOS` (файлы `*.json`, FIFO), умеет шаг `prompt_tool` (реальный вызов MCP-сервера из `--mcp-config`), на SIGINT отдаёт `result/error_during_execution` и выходит с 0, при пустой очереди — exit 3. Используется с фазы 2; здесь — unit-тест самого скрипта. |
| Образ | `python:3.12-slim` + Node 22 + `@anthropic-ai/claude-code` (пин), non-root `app` с UID/GID из `.env`. Dev-зависимости в образе — нужны контейнерному прогону тестов. |

## Deliverables

- `settings.py`, `settings_local.py.example`, `.env.example`, `.gitignore`, `requirements*.txt`, `pyproject.toml`
- `app/main.py`, `app/app.py`, `app/store/{db,repos}.py`, `app/store/migrations/0001_init.sql`,
  `app/transport/{bot,middleware,handlers,sender,outbox,texts}.py`, `app/core/topics.py`
- `Dockerfile`, `docker-compose.yml`, `docker-compose.test.yml`, `docker-compose.override.yml.example`
- `scripts/test.sh`, `scripts/test_docker.sh`
- `tests/conftest.py`, `tests/support/{session,spy,updates}.py`, `tests/unit/conftest.py`,
  `tests/fake_claude/claude`, e2e/unit тесты ниже
- `specs/E2E_TESTS.md`, `CHANGELOG.md`, раздел «Project map» в `CLAUDE.md`

## Tests

| Файл | Сценарии |
|---|---|
| `tests/e2e/test_access.py` | чужой пользователь молчит и не создаёт тему; чужой callback получает тост; `ALLOWED_CHATS` блокирует чужой чат; разрешённый получает `/help` |
| `tests/e2e/test_commands.py` | `/whoami`; `/status` создаёт тему с `DEFAULT_CWD`; `/topics` пуст/непуст; сообщение в теме форума создаёт тему с `thread_id`; reply-тред в группе темой не считается; `/start` = `/help` |
| `tests/e2e/test_outbox.py` | доставка и `delivered_message_id`; сетевая ошибка → повтор; `RetryAfter` откладывает только свою тему; порядок внутри темы; протухшая строка → `failed` |
| `tests/e2e/test_dedup.py` | один `update_id` дважды → один ответ |
| `tests/e2e/test_lifecycle.py` | `NOTIFY_CHAT` получает 🌅 при старте и ⏹ при остановке |
| `tests/unit/test_fake_claude.py` | init + сценарий + лог stdin; пустая очередь → exit 3 |

## Phase results

- Всё из Deliverables на месте; `bash scripts/test.sh` — 20 passed (18 e2e, 2 unit).
- Тест порядка доставки поймал баг в первой версии outbox-воркера: после сбоя головной строки
  темы воркер брал следующую строку темы, пока головная ждала повтора. Исправлено: сначала
  выбирается голова очереди каждой темы, и только потом проверяется `next_attempt_at`
  (`HEAD_OF_QUEUE` в `repos.py`).
- Recording-сессия отделяет `failed_calls` (внедрённые сбои) от `calls`, чтобы spy показывал
  только то, что Telegram принял.
- aiogram-методы содержат sentinel `Default` в необязательных полях: в outbox и в записи
  сессии используется `model_dump(exclude_none=True, exclude_defaults=True, mode="json")`.
- Роутер создаётся фабрикой `build_router()`: модульный `Router` нельзя подключить к двум
  `Dispatcher` (каждый тест создаёт свой `App`).
- Отклонение: unit-тест fake `claude` не покрывает шаг `prompt_tool` и SIGINT — они получают
  тесты в фазах 5 и 2 соответственно, где используются.
- Проверка resume хостовой сессии из контейнера — в smoke-чеклисте (нужен живой запуск).

## Manual smoke checklist

1. `cp .env.example .env`, `cp settings_local.py.example settings_local.py`, заполнить токен и `ALLOWED_USERS`.
2. `docker compose up -d --build` → в `NOTIFY_CHAT` пришло `🌅`.
3. `/whoami`, `/status`, `/topics` отвечают; чужой аккаунт — тишина.
4. Проверка resume хостовой сессии из контейнера (перенос из фазы 0): `docker compose exec bot claude -p --resume <id хостовой сессии> "what did we discuss"` при смонтированном `CLAUDE_HOME`.

## Open questions

- Нужен ли `git`/`ssh` в образе уже сейчас — `git` ставится (нужен `claude` для repo-детекции), ssh — нет.
