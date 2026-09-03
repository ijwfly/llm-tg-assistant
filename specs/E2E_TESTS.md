# E2E_TESTS — тестовая инфраструктура и покрытие

Status: фаза 6 — инфраструктура, команды, outbox, ходы, стриминг, кнопки, входной конвейер, разрешения/вопросы/планы, сессии и темы; обновляется каждой фазой.

## Запуск

- `bash scripts/test.sh [pytest args]` — поднимает `db-test` из `docker-compose.test.yml`
  (Postgres 16 на порту `TEST_DB_PORT`, по умолчанию 55432, данные в tmpfs), ждёт `pg_isready`,
  запускает `pytest` из `.venv`, гасит контейнер через `trap` (и при падении). Если контейнер
  уже запущен — не трогает его.
- `bash scripts/test_docker.sh` — собирает образ и гоняет тот же набор внутри compose.
- `pyproject.toml`: `asyncio_mode = auto`, session-scoped loop; маркеры не нужны.

## Инфраструктура

| Компонент | Где | Что делает |
|---|---|---|
| Настройки | `tests/conftest.py` (верх файла) | Присваивает `settings.*` до импорта `app`: тестовый токен, `ALLOWED_USERS=[1]`, `DATABASE_URL` из `TEST_DATABASE_URL`, тайминги outbox ≈ 0.02 с. Autouse-фикстура `restore_settings` откатывает изменения после каждого теста. |
| БД | `db` (session), `clean_db` (autouse) | Реальный Postgres с реальными миграциями; после каждого теста `TRUNCATE … RESTART IDENTITY CASCADE` в FK-безопасном порядке. |
| Transport mock | `tests/support/session.py` `RecordingSession` | Подкласс `BaseSession` aiogram: пишет `(имя метода, payload)` в `calls`, возвращает объекты aiogram по `__returning__` (`Message` с растущим `message_id` от 1000, `User` для `getMe`, `True` для bool). `fail_next(method, exc)` — внедрить исключение в следующий вызов; такие вызовы попадают в `failed_calls`, а не в `calls`. `session.files[file_id] = bytes` — содержимое, которое отдаст `getFile`/`download`. |
| Spy | `tests/support/spy.py` `TelegramSpy` | `sent_texts(chat_id)` (тексты, rich-markdown, правки, подписи документов), `last_text()`, `calls(method)`, `assert_shown_text_contains()`, `assert_nothing_sent()`. Drafts — через `calls("SendRichMessageDraft")`. |
| Апдейты | `tests/support/updates.py` | `text_update(text, user_id, chat_id, chat_type, thread_id, is_topic, topic_name)`, `callback_update(data, message_id, …)`, `stopped_update(draft_id)`, `message_update(text|caption, photo_id, document=(id, name, size), voice_id, forward_from, forward_channel, media_group_id, reply_to)`, `edited_update(text, message_id)` — настоящие `aiogram.types.Update`. |
| Прогон | `tests/support/helpers.py` | `feed(app, update)` → `dp.feed_update` (реальные middleware и хендлеры); `wait_outbox_idle(app)` — ждёт, пока все due-строки outbox доставлены/провалены; `run()` = оба; `wait_for_text(spy, fragment)` — ждёт появления текста; `wait_turn_finished(app)` — ждёт конца последнего хода и возвращает строку `turns`. |
| Приложение | фикстура `app` | `App(Bot(session=RecordingSession()), db)` со стартом outbox-воркера; `stop()` в teardown. |
| fake `claude` | `tests/fake_claude/claude`, фикстура `fake_claude` (autouse) в `tests/support/fake_claude.py` | Исполняемый скрипт stream-json (см. `PHASE_1_SKELETON.md`). Фикстура даёт каждому тесту свою очередь сценариев и лог, подменяет `CLAUDE_BIN`, `CLAUDE_ENV`, `WORK_ROOT`/`DEFAULT_CWD` (в `tmp_path/work`). Хелперы: `enqueue(*events)`, `text_turn(text, **result)`, `argv_calls()`, `cwds()`, `stdin_texts()`, `signals()`; билдеры событий `assistant_text`, `result`, `text_delta`, `thinking_delta`, `tool_use`, `tool_result`, `compact_boundary`, `permission_denied`. Шаги сценария `{"delay": s}` и `{"exit": code, "stderr": …}` моделируют долгий ход и падение; `prompt_tool(tool, input)` — fake реально запускает `app/bridge/mcp_server.py` из `--mcp-config` и блокируется до решения по сокету, решения читаются `decisions()`; `question(q(...))` строит вход `AskUserQuestion`. Сокет каждого теста — короткий путь из `tempfile` (`settings.BRIDGE_SOCKET`). `CLAUDE_CONFIG_DIR` = `tmp_path/claude`; `write_transcript(cfg, cwd, id, prompts, custom_title, ai_title, summary, mtime, sidechain)` пишет транскрипт для индекса сессий. `RecordingSession` строит `ForumTopic` (thread id от 100) для `createForumTopic`. `wait_turn_finished(app, after=id)` ждёт ход новее `id`. |
| Unit | `tests/unit/` | `conftest.py` переопределяет `db`/`clean_db` заглушками: БД не нужна. |

## Что покрывает каждый файл

| Файл | Конвейер | Сценарии |
|---|---|---|
| `e2e/test_access.py` | Update → `AccessMiddleware` | чужой пользователь — тишина и нет темы; чужой callback — тост `Not authorized`; `ALLOWED_CHATS`; разрешённый получает `/help` |
| `e2e/test_commands.py` | Update → middleware → хендлеры → `TopicService` → outbox | `/whoami`; `/status` создаёт тему с `DEFAULT_CWD`; `/topics`; тема форума с `thread_id` и названием; reply-тред группы не тема; `/start` = `/help`; текст создаёт тему и пользователя |
| `e2e/test_turns.py` | сообщение → `TopicRuntime` → fake `claude` → события → rich-ответ → outbox → `message_links` | ход и ответ, `turns` со статистикой, argv с `--session-id`; второй ход в тот же процесс; `✔️` без текста; `🧹` compact; `⚠️` ошибка; `⏹` лимит; `🔒` отклонённые; reply-цитаты (бот/чужой); `/cost` уходит в Claude; `/clear` = новый контекст; подпись статистики |
| `e2e/test_turn_queue.py` | очередь темы | хинт один раз и порядок ответов; переполнение очереди |
| `e2e/test_turn_control.py` | `/cancel`, таймаут, падения, `/retry` | SIGINT → `🛑` и resume; отмена без хода; `⏱`; падение с незаметным повтором; двойное падение `💥` со stderr; `/retry` повторяет промпт |
| `e2e/test_process_lifecycle.py` | процесс темы | простой → стоп → resume того же id; `/stop`; `/new`; `/cd` внутри/вне корня и несуществующая; `/go`; смена session id по `result`; остановка демона посреди хода → `⏹`, процесс убит, `turns.status=aborted`; `/status` с процессом и последним ходом |
| `e2e/test_outbox.py` | `TelegramSender` → `outbox` → `OutboxWorker` → сессия | `delivered_message_id`; сетевая ошибка → повтор; 429 паркует только свою тему; порядок внутри темы при повторе; протухшая строка → `failed`; отвергнутый rich → plain fallback и `message_links`; правка «не изменено» = доставлено; постоянный Bad Request → `failed`, очередь темы не блокируется |
| `e2e/test_streaming.py` | события → `LiveView` → drafts / сообщение-прогресс → outbox | draft с `<tg-thinking>`, следом, thinking и удержанным последним словом, `can_stop`; нативный Stop → `🛑` с кнопкой повтора; отвергнутый draft → сообщение-прогресс с `🛑`, удаление после ответа; группа: прогресс, правки, удаление после финала; кнопка `🛑` → отмена и тост; склейка короткого сегмента; 429 на draft не ломает ход; длинный ответ → файл |
| `e2e/test_cards.py` | `/status` → карточка → callbacks → `actions` | кнопки карточки; `🛑` при идущем ходе; `🆕` перерисовывает карточку; `⏸`/`🔄`; `✖` удаляет; устаревшая кнопка → тост; `🔁` на вердикте; `🔓` → `acceptEdits` и новый argv; `▶️ Продолжить`; `/perm`; меню из 3 команд |
| `e2e/test_ingest.py` | Update → `Batcher` → `Ingest.build_item` (скачивание, транскрипция) → staging или `assemble` → ход | альбом с подписью → один ход с двумя image block и файлами в inbox; текст+фото+голос за окно → один ход по `message_id`; форвард без вопроса → staging и 👀, затем ход с атрибуцией; форвард канала; `forward_as_prompt`; документ без/с подписью; транскрипция с эхом 🎤; `voice_as_prompt=off`; провал транскрипции → путь; правка → пометка и `✏️`; файл > лимита → предупреждение, вопрос идёт; `/new` чистит staging и карточка показывает `Staging`; `/files`; чистка inbox по TTL; reply-цитата берётся у якоря батча |
| `e2e/test_permissions.py` | `claude` → MCP → сокет → `PromptService` → карточка → callback/текст → решение | карточка Bash и `✅` → allow с `updatedInput`, argv с prompt tool; `❌` → deny; `🔓 Всегда` → `updatedPermissions localSettings` + `topic_rules` + `/perm`; Edit-карточка с diff без «Всегда»; `✏️` → следующий текст = причина, ход не создан; таймаут → deny и `⌛`; повторное нажатие → тост; `/cancel` при ожидании → deny и `🛑`; `🔐 жду разрешения` в draft и `/status`; Write новый файл и MCP-инструмент с маскированием; `dontAsk` без prompt tool; `/perm forget` чистит файл и таблицу; рестарт помечает `stale` |
| `e2e/test_questions.py` | `AskUserQuestion` → карточки | один вариант → `answers` и `→ label`; multiSelect тогглы и `Готово`; два вопроса подряд; `✍ Свой ответ` → текст; таймаут |
| `e2e/test_plans.py` | `ExitPlanMode` → карточка плана | `✅ без вопросов` → `setMode acceptEdits` + режим темы; `спрашивать про правки` → `setMode default`; `✏️ Доработать` → deny с текстом |
| `e2e/test_sessions.py` | `/sessions`, `/resume` → индекс транскриптов → тема | карта всей машины: своя папка первой, пометки «эта тема / эта тема, раньше», кнопки `Продолжить здесь`/`Новая тема`, подвал про сессии вне `WORK_ROOT`; `Новая тема` → тема под папку сессии с `--resume`; прошлая сессия после `/new`; пусто; `/resume` по префиксу → id/resumable и `--resume` в argv; переезд в cwd сессии; недоступная cwd → остаёмся с предупреждением; без аргумента/неизвестная/неоднозначная/по имени/полный id; кнопка `🔗`; `/status` с заголовком |
| `e2e/test_topics_create.py` | `/branch`, `/project` → `CreateForumTopic` (прямой) → новая тема | `/project new` создаёт папку, сессию и тему (существующая папка — только тема), плохие имена и подсказка; ветка: тема с `fork`, сообщения в обеих, первый спавн `--resume src --fork-session --name`, новый id принят и fork снят, второй спавн без fork; `🌿` с карточки для терминальной сессии; `/project` по алиасу и пути, ход в новой теме в её cwd; без аргумента, плохой путь, отказ Telegram |
| `e2e/test_rename.py` | `/rename`, implicit-темы | `EditForumTopic` + БД + тихий ход `/rename`; без имени; implicit-тема названа по первому промпту один раз; явное имя не трогается |
| `e2e/test_dedup.py` | `DedupMiddleware` | один `update_id` дважды → один ответ |
| `e2e/test_lifecycle.py` | `App.start/stop` | `NOTIFY_CHAT` получает 🌅 и ⏹ (с `message_thread_id`) |
| `unit/test_fake_claude.py` | скрипт fake `claude` | init с `--session-id`, воспроизведение сценария, лог; пустая очередь → exit 3 |
| `unit/test_markdown_split.py` | `render/markdown.py` | разрезка по строкам, fence-aware разрез с переоткрытием языка, границы абзацев, таблица целиком, правила превью |
| `unit/test_classify.py` | `ingest/classify.py`, `InboxService.unique_path` | матрица prompt/staging/skip, атрибуция форвардов, санитайзер имён, суффиксы коллизий |
| `unit/test_rules.py` | `bridge/rules.py` | матрица «Всегда», форма `updatedPermissions`, `forget_rules` от cwd до корня |
| `unit/test_cards.py` | `render/cards.py` | карточки Bash/Edit/Write/Read/Web/прочие, fence с backticks, обрезка diff, маскирование |
| `unit/test_mcp_server.py` | `bridge/mcp_server.py` как процесс | initialize/tools/list/ping; нет сокета → deny без зависания; решение демона проксируется с токеном |
| `unit/test_sessions_index.py` | `bridge/sessions.py` | sanitize cwd; приоритет заголовков и порядок по mtime; пропуск isMeta/tool_result/команд, metadata-only; sidechain и обрезка 200; поиск по id/префиксу/имени между проектами |
| `unit/test_progress.py` | `render/progress.py` | детали инструментов и срезы, строка прогресса, след из трёх с подагентом, стабильная фраза, состояние ожидания, рендер draft/прогресса |

## Not yet covered

| Пробел | Причина | Приоритет |
|---|---|---|
| Реальный `claude`, реальный Telegram | По определению вне suite; закрывается smoke-чеклистами фаз | — |
| `docker compose up` целиком | Проверяется `scripts/test_docker.sh` и smoke | средний |
| Падение воркера outbox посреди доставки (демон убит между отправкой и `mark_delivered`) | Требует убийства процесса; поведение at-least-once описано в спеке | низкий |
| Очистка `processed_updates` по возрасту | Нет периодической задачи в фазе 1 | низкий, фаза 9 |
| Fallback `--resume` → `--session-id` при неудачном resume | Нужен fake-сценарий «выход до init»; ветка есть в `runtime._run_turn` | средний |
| `createForumTopic` в реальной личке с topics | Только smoke | — |
| Реакция 👾 на якорь при ошибке хода | Не реализована в фазе 4 (только 👀 на staging) | низкий, фаза 8 |
| Обрыв MCP-клиента (claude умер) при висящей карточке → `🛑` | Ветка `watch` в `PromptService.handle`; fake гасится только SIGINT'ом, который уже резолвит запрос через `cancel()` | низкий |
| Параллельные prompt-запросы (несколько tool-вызовов сразу) | MCP-сервер обрабатывает по одному; сценарий последователен | низкий |
| Keepalive draft'а при долгом инструменте | Таймер есть (`DRAFT_KEEPALIVE`), тест на повторную отправку без изменений не написан | низкий |
| Потеря сообщения-прогресса (удалено пользователем) → пересоздание | Ветка в `LiveView._send_latest` | низкий |
