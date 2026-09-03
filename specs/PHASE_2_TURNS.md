# PHASE_2_TURNS — процесс `claude` и ход в чате

Status: all phases done — процесс, ходы, команды, вердикты; tests green (55 passed)

## Why

После фазы 1 бот умеет только принимать команды. Эта фаза даёт главное: сообщение в теме
становится ходом Claude Code, ответ приходит в чат, процесс живёт между ходами, ход можно
прервать, повторить, а контекст — начать заново или перенести в другую директорию. Стриминг,
батчер, медиа и кнопки разрешений — следующие фазы; здесь ответ доставляется целиком по
завершению каждого текстового блока.

## Verified facts

Из фазы 0 (`PHASE_0_SPIKE.md`): формат stream-json, `--verbose` обязателен, `assistant` по
одному блоку, `result` завершает ход, SIGINT завершает ход и процесс, `--resume` из другой cwd,
`system/permission_denied` и `result.permission_denials` при `dontAsk`/без prompt tool.

Дополнительно проверено при написании фазы:

- `claude -p --resume <id>` с несуществующим id завершается с ошибкой на stdout/stderr
  (`No conversation found with session ID`) — assumed по докам `sessions`, покрыто fallback'ом
  на `--session-id` (см. Decisions).
- В режиме `default` без `--permission-prompt-tool` всё, что требует подтверждения,
  отклоняется с событием `system/permission_denied` (spike 9 с `--permission-prompts none` —
  тот же путь).

## Decisions

| Вопрос | Решение |
|---|---|
| Разрешения в этой фазе | Prompt tool появится в фазе 5. Сейчас режим темы `prompt` → `--permission-mode default` без prompt tool: спорные вызовы отклоняются, список отклонённых приходит в конце хода (`🔒 Отклонено без спроса`). Остальные режимы — как в спеке. |
| Процесс на тему | `TopicRuntime` (в памяти, `RuntimeRegistry` по `topic_id`): очередь ходов (`TURN_QUEUE_MAX`), воркер-задача, процесс, таймер простоя. Один ход за раз. |
| Первый запуск vs resume | `topics.session_id` выдаётся при первом ходе; `topics.session_resumable=false` до первого `result`. Спавн: `--session-id` пока не resumable, иначе `--resume`. Если `--resume` падает до `init` — один повтор с `--session-id` того же uuid. |
| Смена session id | `init`/`result` с другим `session_id` (после `/compact`, `/clear` внутри процесса) → тема принимает новый. |
| Отмена | `/cancel` и `stopped_message_generation` вне очереди: SIGINT; CLI отдаёт `result/error_during_execution` и выходит; вердикт `🛑 Прервано.`; следующий ход — `--resume`. |
| Лимит хода | `TURN_TIMEOUT_SECS` → SIGINT, вердикт `⏱`. |
| Падение | EOF без `result` (или exit≠0): один незаметный повтор хода с новым процессом; второе падение — `💥 Процесс claude завершился (код N).` + хвост stderr (≤ 12 строк, токены вырезаны) + `/retry`. |
| Доставка текста | Каждый `assistant[text]` → `SendRichMessage(markdown)` как есть, разрезка по строкам на 30 000 (fence-aware сплиттер — фаза 3). `TelegramBadRequest` на rich → тот же текст plain-сообщениями по 4 000 (в outbox-воркере). |
| Индикация | `sendChatAction typing` каждые 4 с, пока идёт ход; напрямую (не через outbox — эфемерно). Строка прогресса/draft — фаза 3. |
| Ход из сообщения | Только текст/подпись (медиа и батчер — фаза 4). Reply → префикс `[в ответ на твой ответ: «…»]` / `[в ответ на сообщение: «…»]` (≤ 700 символов; корень темы не цитируется). Неизвестные `/команды` уходят как есть; `/clear` = `/new`. |
| Сообщение во время хода | В очередь; один раз на ход `🕐 Дописываю текущий ход — это следующим.`; очередь полна → `⚠️ Очередь полна, повтори позже.` |
| Хранение ходов | `turns` (prompt для `/retry`, статус, статистика). `outbox` получает `topic_id/turn_id/role`, воркер после доставки пишет `message_links`. |
| Остановка демона | Идущие ходы получают `⏹ Демон остановлен посреди хода…`, процессам — `PROCESS_STOP_GRACE_SECS` на выход (закрыть stdin → SIGTERM → SIGKILL), очередь ходов теряется (сообщения останутся в Telegram, пользователь повторит). |
| `/cd` | Путь раскрывается (`~`), должен существовать и лежать внутри `WORK_ROOT` (по `realpath`); контекст заново. `/go` — алиасы `PROJECTS`. |
| Окружение `claude` | Из окружения демона вырезаются `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `POSTGRES_*`, `CLAUDECODE`, `CLAUDE_CODE_*`; добавляются `CLAUDE_CONFIG_DIR` (если задан) и `CLAUDE_ENV` из настроек (тесты передают через него сценарии fake `claude`). |

## Deliverables

- `app/store/migrations/0002_turns.sql`; `TurnsRepo`, `topics.session_resumable`, `outbox.topic_id/turn_id/role`
- `app/bridge/cli.py` (argv + env), `app/bridge/process.py` (`ClaudeProcess`), `app/bridge/events.py` (разбор событий)
- `app/core/runtime.py` (`TopicRuntime`, `RuntimeRegistry`, `TurnRequest`)
- `app/render/markdown.py` (`split_text`)
- `app/transport/handlers.py`: `/new` `/clear` `/stop` `/cancel` `/retry` `/cd` `/go` `/status`, сообщение → ход; `stopped_message_generation` → cancel
- `app/transport/outbox.py`: rich → plain fallback, `message_links`
- новые настройки: `IDLE_TIMEOUT_SECS`, `TURN_TIMEOUT_SECS`, `TURN_QUEUE_MAX`, `SHOW_TURN_STATS`, `TYPING_INTERVAL`, `PROCESS_STOP_GRACE_SECS`, `CLAUDE_ENV`, `ALLOWED_TOOLS`, `DISALLOWED_TOOLS`, `CLAUDE_SETTINGS`, `ADD_DIRS`, `MAX_BUDGET_USD_PER_TURN`, `FALLBACK_MODEL`
- `tests/support/fake_claude.py` (фикстура), тесты ниже; `specs/E2E_TESTS.md`, `CHANGELOG.md`, `CLAUDE.md`

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_turns.py` | текст → rich-ответ, `turns` со статистикой, `session_id` в теме, argv с `--session-id`; второй ход в тот же процесс без нового argv; ход без текста → `✔️`; `compact_boundary` → `🧹`; `is_error` → `⚠️`; `permission_denials` → `🔒`; reply-цитата в промпте; неизвестная `/команда` уходит в Claude; `/clear` = `/new` |
| `e2e/test_turn_queue.py` | сообщение во время хода → хинт один раз и выполнение после; переполнение очереди |
| `e2e/test_turn_control.py` | `/cancel` → SIGINT → `🛑` и следующий ход через `--resume`; `/cancel` без хода; таймаут хода → `⏱`; падение → незаметный повтор; двойное падение → `💥` со stderr; `/retry` |
| `e2e/test_process_lifecycle.py` | простой → процесс гаснет, следующий ход `--resume` того же id; `/stop`; `/new` → новый id; `/cd` внутри/вне `WORK_ROOT`; `/go`; init с другим session_id меняет тему; остановка демона посреди хода → `⏹` |
| `e2e/test_outbox.py` (+) | rich отвергнут → plain fallback; `message_links` после доставки |
| `unit/test_markdown_split.py` | разрезка по строкам, длинная строка, пустой текст |

## Phase results

- Всё из Deliverables; `bash scripts/test.sh` — 55 passed (49 e2e, 6 unit), ~15 с.
- `session_id` теперь выдаётся при создании темы (иначе первый спавн шёл с `--session-id None`);
  после отмены/таймаута сессия помечается resumable, если был получен `init`.
- Fallback `--resume` → `--session-id` при выходе процесса до `init` реализован, но не покрыт
  тестом (нужен сценарий fake `claude` «выход до init» — в `E2E_TESTS.md` «Not yet covered»).
- Хендлер `stopped_message_generation` → cancel зарегистрирован; drafts и тест — фаза 3.
- Живая проверка фазы 1 показала, что бот на хосте нельзя пускать на тестовую БД (тесты
  чистят таблицы): для ручных прогонов — отдельная dev-БД (`docker run … -p 55433`).
- Отклонение: `/status` и `/topics` показывают состояние процесса из памяти демона; после
  рестарта «Последний ход» пуст (как в claude-tg).

## Manual smoke checklist

1. В теме: «что в этой директории?» — typing, затем rich-ответ; `/status` показывает сессию и
   «Последний ход».
2. Уточнение reply'ем на ответ бота — модель видит цитату.
3. `/cancel` посреди длинного хода → `🛑`; `/retry` повторяет.
4. `/new` → следующий ход не помнит предыдущего; `/resume` пока нет (фаза 6).
5. `/cd ~/src/other` → «контекст заново»; `/cd /etc` → отказ.
6. `/compact` → `🧹`; `/cost` → текст от Claude Code.
7. Попросить правку файла в режиме `prompt` → в конце хода `🔒 Отклонено без спроса: Edit` (кнопки — фаза 5).

## Open questions

- Стоит ли отправлять `assistant[text]` короче 120 символов сразу (склейка сегментов — фаза 3).
