# PHASE_8_EXTRAS — файлы наружу, вывод инструментов, подагенты, реакция на ошибку, rewind

Status: phase 1 of 3 — `send_file`

## Why

Остатки матрицы поддержки (PROJECT_SPEC §5): модель не может отправить файл в чат; вывод
инструментов и текст подагентов не виден; ошибка хода не отмечается на сообщении; откат файлов
(`--rewind-files`) не доступен. Дополнений пользователя (раздел 12) нет.

## Verified facts

- MCP-сервер моста уже поднимается `claude` из `--mcp-config`; второй инструмент — ещё одна
  запись в `tools/list` и тот же сокет (`{tool: "send_file", args}`).
- `user[tool_result]` события приходят с `tool_use_id` и `content` (строка или список блоков),
  `parent_tool_use_id` для подагентов (spike 6). Текст подагентов — только с
  `--forward-subagent-text` (docs).
- Rich-markdown Telegram поддерживает `<details>` (spec 2.2). Лимит plain — 4 000.
- `setMessageReaction` с 👾 доступен боту (spec 2.2).
- **Assumed** (spike в фазе 3 этой спеки): `claude -p --resume <id> --rewind-files <uuid>` с
  `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING=true` откатывает Write/Edit до чекпойнта user-сообщения.

## Decisions

| Вопрос | Решение |
|---|---|
| `send_file` | Инструмент `mcp__tgbridge__send_file {path, caption?}` (флаг `BRIDGE_SEND_FILE_TOOL`, on). Путь — абсолютный или от cwd темы; должен существовать и лежать внутри `WORK_ROOT` или `ADD_DIRS`; ≤ 50 МБ. jpg/png/gif/webp → фото (`sendPhoto`), остальное — документ; подпись ≤ 1024. Возврат модели: `File <имя> (<размер>) sent to the chat.` или `Error: …`. Свой инструмент моста **не спрашивает разрешение**: prompt-запрос на `mcp__tgbridge__send_file` разрешается автоматически (это отправка файла из рабочей папки в чат самого пользователя). Преамбула описывает инструмент. |
| Вывод инструментов | Флаг темы `verbose_tools` (кнопка «Вывод инструментов» на «Ещё», дефолт `VERBOSE_TOOL_OUTPUT` off): каждый `tool_result` главной сессии → rich-сообщение `<details><summary>Read main.py</summary>` + ` ``` ` содержимое ≤ 3 500 символов `</details>` (fallback plain при отказе Telegram). Ошибочный результат — `⚠️` в summary. Имя и деталь — из `tool_use` по `tool_use_id`. |
| Подагенты | `FORWARD_SUBAGENT_TEXT` (off) → argv `--forward-subagent-text`; текстовые блоки с `parent_tool_use_id` → `<details><summary>Подагент</summary>…</details>` (только когда флаг включён; иначе игнор, как сейчас). |
| 👾 на ошибке | Ход завершился `error`/`crashed`/`timeout` → реакция 👾 на якорное сообщение батча (если `REACTIONS` и флаг пользователя `reactions`); `TurnRequest.anchor` = `(chat_id, message_id)`. |
| Rewind | Фаза 3: spike на реальном CLI; при успехе — `FILE_CHECKPOINTING` (env), `turns.checkpoints` (uuid user-сообщений из `--replay-user-messages`), `/rewind` — список последних 5 ходов с чекпойнтами кнопками `Откатить: «<промпт…>»` → подтверждение → одноразовый `claude -p --resume <id> --rewind-files <uuid>`; при неуспехе — остаётся ◐ с описанием причины. |
| Задачи из hooks | Не делаем (опционально по спеке; `TaskCreated` требует `--include-hook-events` и живое сообщение) — открытый вопрос. |
| fake `claude` | Шаг `{"mcp_tool": {"name": "send_file", "arguments": {...}}}` — вызывает инструмент MCP-сервера и пишет `{"mcp_result": <text>}`; `tool_result` со строкой/списком блоков и `is_error`. |

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | `send_file`: MCP-инструмент, сокет, отправка фото/документа, авто-allow, преамбула | ⏳ |
| 2 | `verbose_tools`, `FORWARD_SUBAGENT_TEXT`, 👾 на ошибке | ⏳ |
| 3 | Rewind: spike, затем `/rewind` или отказ; документация | ⏳ |

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_send_file.py` | фото → `SendPhoto` с подписью, документ → `SendDocument`, ответ модели `File … sent`; путь вне корня / нет файла / > 50 МБ → `Error`; флаг off → инструмента нет в `tools/list`; prompt-запрос на `send_file` разрешается без карточки |
| `e2e/test_verbose.py` | `verbose_tools` on → `<details>` с именем инструмента и содержимым, обрезка, `⚠️` при ошибке; off → ничего; подагент с флагом → `<details>` и argv; 👾 на якоре при ошибке хода, нет при успехе |
| `unit/test_fake_claude.py` | шаг `mcp_tool` |

## Phase results

_(заполняется по ходу)_

## Manual smoke checklist

1. «Сделай скриншот структуры проекта в файл tree.txt и отправь мне его» → документ в теме.
2. «Ещё» → «Вывод инструментов: вкл» → вопрос с чтением файла → свёрнутые `<details>`.
3. Ход с ошибкой (например, `/cost` в dontAsk… или отмена) → 👾 на сообщении.

## Open questions

- Задачи из `TaskCreated` hooks — живой чек-лист; не делаем.
