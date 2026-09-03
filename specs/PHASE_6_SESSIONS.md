# PHASE_6_SESSIONS — сессии и темы

Status: phase 1 of 3 — индекс сессий, `/sessions`, `/resume`

## Why

Тема = сессия, но пока связь односторонняя: тема рождает сессию, а подхватить чужую
(терминальную) сессию, отпочковать ветку или завести тему под проект из чата нельзя. Эта
фаза реализует PROJECT_SPEC 4.2 и строки `/sessions`, `/resume`, `/branch`, `/project`,
`/rename` таблицы 4.3.

## Verified facts

- Транскрипты: `$CLAUDE_CONFIG_DIR/projects/<cwd, не-alnum→'-'>/<session-id>.jsonl` (spike 5;
  для путей > 200 символов CLI добавляет хэш-суффикс — не поддерживаем, помечено).
- Заголовок сессии (из исходников `claude-agent-sdk` 0.2.152 `_internal/sessions.py`):
  `customTitle` (строка `{"type":"custom-title","customTitle":…}`) > `aiTitle` > `lastPrompt`
  > `summary` (хвост файла) > первый осмысленный user-промпт (не `tool_result`, не `isMeta`,
  не `isCompactSummary`, не `<command-name>`), обрезка 200. Sidechain-файлы (первая строка
  `"isSidechain":true`) пропускаются. `cwd` — из первой записи с полем `cwd`.
- `--resume <id>` ищет сессию по всем проектам машины; `--fork-session` даёт новый id
  (в `init.session_id`), `--name` пишет `custom-title` в форк (spike 5).
- aiogram: `CreateForumTopic(chat_id, name, icon_color, icon_custom_emoji_id)` → `ForumTopic`
  (`message_thread_id`, `name`, `icon_color`, `is_name_implicit`); `EditForumTopic(chat_id,
  message_thread_id, name)` → bool; `ForumTopicCreated.is_name_implicit`. Цвета иконок: 6
  фиксированных (`0x6FB9F0 0xFFD67E 0xCB86DB 0x8EEE98 0xFF93B2 0xFB6F5F`).
- **Assumed**: `createForumTopic` в личном чате с включёнными topics работает у бота (по
  докам 9.3+; проверяется smoke).

## Decisions

| Вопрос | Решение |
|---|---|
| Индекс сессий | Свой stdlib-модуль `app/bridge/sessions.py` (голова 64 КБ + хвост 16 КБ файла, без полного парса), а не зависимость `claude-agent-sdk`. `list_sessions(cwd, limit=8)`, `find_session(query)` по всем проектам: полный id, префикс ≥ 4 символов, имя (customTitle, без учёта регистра). Несколько совпадений → список. |
| `/sessions` | Карточка 4.3.1: `▸ 3f2a9c1d · 5 мин назад · «title» · эта тема / тема <имя> / терминал`; на строку кнопки `🔗 3f2a9c1d` (`rs:<topic>:<id8>`) и `🌿` (`br:<topic>:<id8>`). Пусто → `В <dir> сессий пока нет.` Кнопки `📜 Сессии` и `🌿 Ветка` на карточке темы. |
| `/resume` | Процесс гасится; `session_id` = найденный, `session_resumable = true`; если `cwd` сессии — существующая директория внутри `WORK_ROOT`, тема переезжает в неё, иначе остаётся с предупреждением. Staging не трогаем. Предупреждение про открытый терминал не делаем (нет надёжного признака). |
| `/branch [имя]` | Новая тема (см. «создание тем») с `settings.fork = {"from": <src id>, "name": имя?}` и `session_id = src`, `session_resumable = true`. Первый спавн: `--resume <src> --fork-session [--name имя]`; `init.session_id` (новый) записывается в тему, `fork` снимается. Из `/sessions` — то же с выбранным id. Имя темы = имя ветки или `<имя исходной темы> · ветка`. |
| Создание тем | Только через `createForumTopic` — **прямой вызов Bot API** (результат нужен сразу для строки темы), единственное исключение из «всё через outbox» вместе с live view. Ошибка Telegram (не форум, нет права) → `⚠️ Не могу создать тему: <причина>`. Цвет иконки — по хэшу имени из 6 допустимых. |
| `/project [алиас\|путь]` | Путь через `resolve_cwd` (внутри `WORK_ROOT`); имя темы = алиас или последний компонент; в новой теме `📁 <путь>` / `Тема готова, контекст чистый. Пиши сюда.`, в исходной `✅ Тема <имя> открыта.`; без аргумента — справка со списком `PROJECTS`. |
| `/rename <имя>` | Имя темы в БД + `EditForumTopic` (через outbox; для General/лички без темы — только БД) + ход `/rename <имя>` в Claude Code с флагом `quiet` (вердикт `✔️ без текста` не шлётся). `settings.title_implicit` снимается. |
| Implicit-темы | `ForumTopicCreated.is_name_implicit` → `settings.title_implicit = true`. После первого успешного хода тема переименовывается по первым 40 символам первого промпта (сгенерированный `aiTitle` появляется в транскрипте позже и асинхронно — не ждём) и флаг снимается. |
| `/status` | Строка `Сессия <id> · «заголовок»` — заголовок из индекса (если файл есть). |
| Тесты | `settings.CLAUDE_CONFIG_DIR` в фикстуре указывает в `tmp_path/claude`; хелпер `write_transcript(cwd, session_id, prompts, custom_title=None, ai_title=None)` пишет jsonl нужной формы. `RecordingSession` строит `ForumTopic` для `createForumTopic`. |

## Design

- `app/bridge/sessions.py` — `SessionInfo`, `sanitize_cwd`, `project_dir`, `list_sessions`, `find_session`, `session_title`.
- `app/bridge/cli.py` — `--fork-session`/`--name` по `topic.settings.fork`.
- `app/core/runtime.py` — на `Init` снять `fork`; `TurnRequest.quiet`; после первого `done`-хода переименование implicit-темы.
- `app/core/actions.py` — `sessions_card`, `resume_session`, `branch`, `create_project_topic`, `rename_topic`, `create_topic` (прямой `CreateForumTopic`).
- `app/store/repos.py` — `TopicsRepo.create`, `find_by_session`, `update_settings`.
- `app/transport/handlers.py`, `callbacks.py`, `keyboards.py`, `texts.py`.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Индекс сессий, `/sessions` с кнопками, `/resume` | ⏳ |
| 2 | Создание тем: `/project`, `/branch` (+ `🌿` из карточки), fork при спавне | ⏳ |
| 3 | `/rename`, implicit-темы, заголовок в `/status`, документация | ⏳ |

## Tests

| Файл | Сценарии |
|---|---|
| `unit/test_sessions_index.py` | sanitize cwd; заголовок по приоритету customTitle/aiTitle/lastPrompt/summary/первый промпт; пропуск tool_result/isMeta/command-name и sidechain; сортировка по mtime и лимит; поиск по id/префиксу/имени, неоднозначность |
| `e2e/test_sessions.py` | `/sessions` с пометками и кнопками, пусто; `/resume` префикс → id/resumable/argv `--resume`, переезд cwd; неизвестная; неоднозначная; по имени; кнопка `🔗` |
| `e2e/test_topics_create.py` | `/branch` → `CreateForumTopic`, тема с fork, сообщения в обеих темах, первый спавн `--resume src --fork-session --name`, новый id записан, второй спавн без fork; `🌿` из `/sessions`; `/project alias` и путь, без аргумента, плохой путь, отказ Telegram |
| `e2e/test_rename.py` | `/rename` → `EditForumTopic`, БД, тихий ход `/rename` в claude; implicit-тема переименована после первого хода и только один раз; `/status` с заголовком; кнопки карточки |

## Phase results

_(заполняется по ходу)_

## Manual smoke checklist

1. В личке с topics: `/sessions` в теме этого репозитория показывает терминальные сессии;
   `🔗` на одной из них → «Подключилась», вопрос про контекст той сессии отвечен верно.
2. `/branch тест` → новая тема, в ней модель помнит контекст исходной; `/status` показывает новый id.
3. `/project <alias>` → тема с иконкой, `📁`, ход в ней работает в нужной директории.
4. Создать тему руками в личке, написать вопрос → тема переименована по вопросу.
5. `/rename Новое имя` → тема переименована, в `/sessions` сессия с этим именем.

## Open questions

- Пути длиннее 200 символов (хэш-суффикс CLI) — не поддерживаются индексом.
- Предупреждение «сессия открыта в терминале» — нет признака; можно смотреть `~/.claude/sessions/*.json` по pid позже.
- Переименование по `aiTitle` (когда появится в транскрипте) — можно добавлять в idle-таймер.
