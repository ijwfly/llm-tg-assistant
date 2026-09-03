# PHASE_8_EXTRAS — файлы наружу, вывод инструментов, подагенты, реакция на ошибку, rewind

Status: all phases done — send_file, вывод инструментов, подагенты, 👾, rewind; tests green (192 passed); smoke — у пользователя

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
- **Verified** (spike 2026-09-03, haiku): `claude -p --resume <id> --rewind-files <uuid>` — **отдельная
  операция**: с промптом падает (`--rewind-files is a standalone operation and cannot be used with a prompt`);
  без stdin печатает `Files rewound to state at message <uuid>` и выходит с 0; файл, созданный в этом
  сообщении, исчез (состояние на момент отправки сообщения). uuid должен быть user-сообщением этой
  сессии, иначе `Error: --rewind-files requires a user message UUID`. Два сообщения, поданные в stdin
  разом, CLI склеивает в один ход (queue-operation): второе не получает своего uuid — мост и так шлёт
  следующий ход только после `result`.

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
| 1 | `send_file`: MCP-инструмент, сокет, отправка фото/документа, авто-allow, преамбула | ✅ |
| 2 | `verbose_tools`, `FORWARD_SUBAGENT_TEXT`, 👾 на ошибке | ✅ |
| 3 | Rewind: spike, затем «Откатить файлы»; документация | ✅ |

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_send_file.py` | фото → `SendPhoto` с подписью, документ → `SendDocument`, ответ модели `File … sent`; путь вне корня / нет файла / > 50 МБ → `Error`; флаг off → инструмента нет в `tools/list`; prompt-запрос на `send_file` разрешается без карточки |
| `e2e/test_verbose.py` | `verbose_tools` on → `<details>` с именем инструмента и содержимым, обрезка, `⚠️` при ошибке; off → ничего; подагент с флагом → `<details>` и argv; 👾 на якоре при ошибке хода, нет при успехе |
| `unit/test_fake_claude.py` | шаг `mcp_tool` |

## Phase results

- 192 теста. Вместо `/rewind` — кнопка «Откатить файлы» на «Ещё» (команд-дублей не заводим): список
  последних 5 ходов с чекпойнтами → подтверждение → одноразовый процесс; тема остаётся на той же
  сессии, процесс потом поднимается `--resume`. Чекпойнт пишется всегда (uuid из echo), кнопка и env —
  только при `FILE_CHECKPOINTING`. `send_file` не спрашивает разрешения. Задачи из hooks не делались.

## Manual smoke checklist

1. «Сделай скриншот структуры проекта в файл tree.txt и отправь мне его» → документ в теме.
2. «Ещё» → «Вывод инструментов: вкл» → вопрос с чтением файла → свёрнутые `<details>`.
3. Ход с ошибкой (например, `/cost` в dontAsk… или отмена) → 👾 на сообщении.

## Open questions

- Задачи из `TaskCreated` hooks — живой чек-лист; не делаем.
