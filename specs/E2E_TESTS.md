# E2E_TESTS — тестовая инфраструктура и покрытие

Status: фаза 1 — инфраструктура и первые сценарии; обновляется каждой фазой.

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
| Transport mock | `tests/support/session.py` `RecordingSession` | Подкласс `BaseSession` aiogram: пишет `(имя метода, payload)` в `calls`, возвращает объекты aiogram по `__returning__` (`Message` с растущим `message_id` от 1000, `User` для `getMe`, `True` для bool). `fail_next(method, exc)` — внедрить исключение в следующий вызов; такие вызовы попадают в `failed_calls`, а не в `calls`. |
| Spy | `tests/support/spy.py` `TelegramSpy` | `sent_texts(chat_id)`, `last_text()`, `calls(method)`, `assert_shown_text_contains()`, `assert_nothing_sent()` — что увидел пользователь, без различий plain/rich/edit. |
| Апдейты | `tests/support/updates.py` | `text_update(text, user_id, chat_id, chat_type, thread_id, is_topic, topic_name)`, `callback_update(data, …)` — настоящие `aiogram.types.Update`. |
| Прогон | `tests/support/helpers.py` | `feed(app, update)` → `dp.feed_update` (реальные middleware и хендлеры); `wait_outbox_idle(app)` — ждёт, пока все due-строки outbox доставлены/провалены; `run()` = оба. |
| Приложение | фикстура `app` | `App(Bot(session=RecordingSession()), db)` со стартом outbox-воркера; `stop()` в teardown. |
| fake `claude` | `tests/fake_claude/claude` | Исполняемый скрипт stream-json (см. `PHASE_1_SKELETON.md`); сценарии — JSON-файлы в `FAKE_CLAUDE_SCENARIOS`, лог stdin/argv в `FAKE_CLAUDE_LOG`. Подключается через `settings.CLAUDE_BIN` с фазы 2. |
| Unit | `tests/unit/` | `conftest.py` переопределяет `db`/`clean_db` заглушками: БД не нужна. |

## Что покрывает каждый файл

| Файл | Конвейер | Сценарии |
|---|---|---|
| `e2e/test_access.py` | Update → `AccessMiddleware` | чужой пользователь — тишина и нет темы; чужой callback — тост `Not authorized`; `ALLOWED_CHATS`; разрешённый получает `/help` |
| `e2e/test_commands.py` | Update → middleware → хендлеры → `TopicService` → outbox | `/whoami`; `/status` создаёт тему с `DEFAULT_CWD`; `/topics`; тема форума с `thread_id` и названием; reply-тред группы не тема; `/start` = `/help`; заглушка на текст и запись пользователя |
| `e2e/test_outbox.py` | `TelegramSender` → `outbox` → `OutboxWorker` → сессия | `delivered_message_id`; сетевая ошибка → повтор; 429 паркует только свою тему; порядок внутри темы при повторе; протухшая строка → `failed` |
| `e2e/test_dedup.py` | `DedupMiddleware` | один `update_id` дважды → один ответ |
| `e2e/test_lifecycle.py` | `App.start/stop` | `NOTIFY_CHAT` получает 🌅 и ⏹ (с `message_thread_id`) |
| `unit/test_fake_claude.py` | скрипт fake `claude` | init с `--session-id`, воспроизведение сценария, лог; пустая очередь → exit 3 |

## Not yet covered

| Пробел | Причина | Приоритет |
|---|---|---|
| Реальный `claude`, реальный Telegram | По определению вне suite; закрывается smoke-чеклистами фаз | — |
| `docker compose up` целиком | Проверяется `scripts/test_docker.sh` и smoke | средний |
| Падение воркера outbox посреди доставки (демон убит между отправкой и `mark_delivered`) | Требует убийства процесса; поведение at-least-once описано в спеке | низкий |
| Очистка `processed_updates` по возрасту | Нет периодической задачи в фазе 1 | низкий, фаза 9 |
| Rich-fallback в plain при ошибке разметки | Rich появляется в фазе 3 | фаза 3 |
