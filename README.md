# llm-tg-assistant

Telegram-бот, который управляет сессиями Claude Code на твоём сервере или ноутбуке. Одна тема в
чате = одна папка и текущая сессия `claude` в ней. Пишешь в тему, как в терминал: текст, фото,
файлы, голосовые, форварды. Ответ приходит живым draft'ом с прогрессом, разрешения на команды и
правки — карточками с кнопками, файлы наружу — вложениями.

Дизайн и решения — в `specs/PROJECT_SPEC.md`, как ведётся разработка — в `CLAUDE.md`.

## Что нужно

- Docker + docker compose (или Python 3.12 и Postgres 16 на хосте).
- Аккаунт Claude с подпиской (OAuth-логин из `~/.claude`) или `ANTHROPIC_API_KEY`.
- Отдельный Telegram-бот от @BotFather. В настройках бота (Bot Settings) включи **Topics** —
  тогда в личном чате с ботом появятся темы, и каждая станет отдельной сессией. Без topics
  бот работает в личке одной сессией и в форум-супергруппах по темам.
- Твой Telegram id (например, у @userinfobot): бот молча игнорирует всех, кто не в списке.

## Быстрый старт (docker compose)

```bash
cp .env.example .env                      # токен, ALLOWED_USERS, пути к проектам и ~/.claude
cp settings_local.py.example settings_local.py   # необязательные переопределения
docker compose up -d --build
docker compose logs -f bot
```

`WORK_ROOT` из `.env` монтируется в контейнер как `/work`: бот работает только внутри него.
`CLAUDE_HOME` (обычно `~/.claude`) даёт контейнеру транскрипты сессий, логин подписки и
`settings.json`. `UID/GID` ставь свои, чтобы файлы, которые правит Claude Code, оставались твоими.

Напиши боту `/status`: появится карточка темы. Дальше просто пиши.

## Запуск на хосте (разработка)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
docker run -d --name llm-tg-dev-db -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app_dev -p 55433:5432 postgres:16
cp settings_local.py.example settings_local.py   # TELEGRAM_BOT_TOKEN, ALLOWED_USERS, DATABASE_URL=postgresql://app:app@localhost:55433/app_dev, WORK_ROOT, DEFAULT_CWD, INBOX_DIR
.venv/bin/python -m app.main
```

Нужен установленный `claude` (`npm i -g @anthropic-ai/claude-code`), залогиненный в подписку.
Тесты: `bash scripts/test.sh` (поднимает свой Postgres в Docker), полностью в контейнере —
`bash scripts/test_docker.sh`.

## Как пользоваться

- **Тема = папка.** Первое сообщение в теме заводит сессию в `DEFAULT_CWD`. `/project <алиас|путь>`
  открывает тему под существующую папку, `/project new <имя>` создаёт папку, сессию и тему.
- **Карточка темы** (`/status`) — пульт: прервать, повторить, новый контекст, стоп процесса, права,
  модель, усилие, сессии, ветка, удалить тему; страница «Ещё» — превью ответа, размышления,
  статистика хода, голосовые ответы, вывод инструментов, реакции, правила «Всегда», откат файлов.
- **Сессии.** Кнопка «Сессии» показывает все сессии Claude Code на машине внутри `WORK_ROOT`,
  включая начатые в терминале. «Продолжить здесь» подхватывает сессию в текущую тему (та же папка),
  «Новая тема» открывает тему под папку другой сессии. Обратно в терминал: `claude --resume <id>`.
  Два писателя в одну сессию одновременно — плохая идея: закрой терминал, прежде чем продолжать в Telegram.
- **Разрешения.** Режим `prompt` (по умолчанию) показывает карточку на каждое действие, которое
  Claude Code не разрешил сам: «Разрешить», «Отклонить», «Всегда: <правило>» (пишется в
  `.claude/settings.local.json` проекта, действует и в терминале), «Отклонить и объяснить».
  `acceptEdits` пропускает правки, `plan` — только план с одобрением, `dontAsk`/`bypass` — без вопросов
  (`bypass` требует `ALLOW_BYPASS = True`).
- **Вопросы и планы** модели приходят кнопками: варианты, «Свой ответ», «Выполнять, правки без
  вопросов» / «спрашивать про правки» / «Доработать план».
- **Медиа.** Фото модель видит как картинку, документы и голосовые сохраняются в inbox и уходят путями,
  голос распознаётся через `TRANSCRIBE_CMD`. Форварды и файлы без подписи копятся (реакция 👀) и уходят
  со следующим вопросом.
- **Команды** (все в меню «/»): `/status`, `/new`, `/project`, `/rename`, `/soul`, `/files`, `/usage`,
  `/help`. Остальные `/команды` (`/compact`, `/cost`, `/context`, skills) уходят в Claude Code как есть.

## Настройки

Дефолты — `settings.py`, переопределения — `settings_local.py` (gitignored) или переменные окружения
для базовых ключей. Самое полезное:

| Ключ | Что делает |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `ALLOWED_CHATS`, `NOTIFY_CHAT` | доступ и уведомления о старте/остановке |
| `WORK_ROOT`, `DEFAULT_CWD`, `PROJECTS`, `NEW_PROJECTS_DIR` | папки: граница, папка новых тем, алиасы, куда `/project new` кладёт папки |
| `DEFAULT_PERMISSION_MODE`, `ALLOW_BYPASS`, `ALLOWED_TOOLS`, `DISALLOWED_TOOLS`, `CLAUDE_SETTINGS`, `ADD_DIRS` | права Claude Code |
| `DEFAULT_MODEL`, `DEFAULT_EFFORT`, `MODEL_CHOICES`, `FALLBACK_MODEL`, `MAX_BUDGET_USD_PER_TURN` | модель и лимиты |
| `SOUL_PATH`, `BRIDGE_PREAMBLE_PATH` | персона и преамбула в системном промпте |
| `TRANSCRIBE_CMD`, `TTS_CMD` | голос: распознавание (`{file}`, `{wav}`) и синтез (`{text_file}`, `{wav}`, `{out}`) |
| `BRIDGE_SEND_FILE_TOOL`, `VERBOSE_TOOL_OUTPUT`, `FORWARD_SUBAGENT_TEXT`, `FILE_CHECKPOINTING` | файлы наружу, вывод инструментов, подагенты, откат файлов |
| `IDLE_TIMEOUT_SECS`, `TURN_TIMEOUT_SECS`, `PERMISSION_TIMEOUT_SECS`, `QUESTION_TIMEOUT_SECS` | таймауты процесса, хода, карточек |
| `USE_DRAFTS`, `STREAM_PREVIEW`, `THINKING_PREVIEW`, `SHOW_TURN_STATS`, `REACTIONS` | показ по умолчанию (переключаются на карточке) |
| `BRIDGE_SOCKET`, `INBOX_DIR`, `INBOX_TTL_DAYS`, `CLAUDE_CONFIG_DIR`, `CLAUDE_BIN` | пути |

Пример голоса на macOS: `TTS_CMD = "say -o {wav} --data-format=LEI16@22050 -f {text_file} && ffmpeg -y -loglevel error -i {wav} -c:a libopus {out}"`.
Для контейнера добавь `ffmpeg`/`whisper` в образ сам: в базовом их нет.

## Эксплуатация

- Логи: `docker compose logs -f bot`. Уровень — `LOG_LEVEL`.
- Перезапуск: `docker compose restart bot`. Идущие ходы получают вердикт `⏹`, кнопка «Повторить»
  повторяет ход; очередь исходящих сообщений (outbox в Postgres) досылается после старта.
- Миграции `app/store/migrations/*.sql` идемпотентны, применяются при инициализации БД и при каждом
  старте бота. Бэкап: `docker compose exec db pg_dump -U app app > backup.sql`.
- Обновление: `git pull && docker compose up -d --build` (версия Claude Code пинится в `Dockerfile`).
- Данные: транскрипты и логин — в `CLAUDE_HOME`, файлы из чата — том `inbox` (`INBOX_TTL_DAYS`),
  состояние тем и очередь — Postgres (`pgdata`).

## Если что-то не так

- Бот молчит — проверь, что твой id в `ALLOWED_USERS`; чужих он игнорирует без ответа.
- Меню «/» показывает старые команды — Telegram кэширует список, переоткрой чат.
- Тему, созданную ботом, нельзя удалить из клиента — это ограничение Telegram; кнопка «Удалить тему»
  на карточке делает это через бота.
- Карточка разрешения зависла — через `PERMISSION_TIMEOUT_SECS` (10 мин) она отклонится сама; если
  Claude Code не видит MCP-сервер моста, проверь `BRIDGE_SOCKET` (сокет должен быть доступен процессу `claude`).
- Сессия «не помнит» контекст после `Продолжить здесь` — сессия открыта ещё и в терминале; закрой его.
