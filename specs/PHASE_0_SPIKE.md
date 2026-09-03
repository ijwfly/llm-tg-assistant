# PHASE_0_SPIKE — эксперименты против реального `claude`

Status: all phases done — 11 прогонов, все вопросы закрыты, результаты перенесены в PROJECT_SPEC §2; tests: n/a (spike)

## Why

Раздел 2 `PROJECT_SPEC.md` содержит факты со статусом **assumed**, от которых зависит дизайн
разрешений, вопросов, планов, отмены и медиа. Их нельзя взять из документации — только
запустить `claude -p` и посмотреть. Результат фазы — обновлённый раздел 2 спеки (assumed →
verified/refuted) и, при необходимости, правки решений в разделе 3.

## Verified facts (до старта)

- `claude` 2.1.259 установлен локально; вложенный запуск требует очистить переменные
  `CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_PID`, `CLAUDE_EFFORT` из окружения.
- В `~/.claude/settings.json` пользователя стоит `permissions.defaultMode: auto` — он
  перекрывает встроенный `default` для `-p`, поэтому режим прав всегда передаём флагом.
- В `claude --help` есть новый флаг `--permission-prompts host|none` (host = SDK-хост или
  `--permission-prompt-tool`; none = всё, что спросило бы, отклоняется). `--permission-mode`
  в help перечисляет `manual` вместо `default`.
- Скрытых в help флагов `--resume-session-at`, `--rewind-files`, `--channels` нет в выводе;
  `--rewind-files` документирован как принимаемый несмотря на это.

## Decisions

| Вопрос | Решение |
|---|---|
| Где живут скрипты | `spikes/` в репозитории (коммитятся как документация эксперимента); результаты — в scratchpad, не коммитятся, выводы — в спеку |
| Модель | `haiku` по умолчанию (дёшево); поведение разрешений от модели не зависит |
| MCP-сервер | Минимальный stdio JSON-RPC на stdlib, логирует каждый `tools/call` и отвечает по политике из JSON-файла |
| Изоляция | Песочница-директория в scratchpad с `git init`; `--strict-mcp-config`; режим прав явно; `CLAUDE_CONFIG_DIR` не подменяем (нужны OAuth-креды) |
| Что не проверяем здесь | Рендер draft в клиентах Telegram (эксперимент 8) — переносится в smoke фазы 3, нужен живой бот |

## Эксперименты

| # | Вопрос | Как | Критерий |
|---|---|---|---|
| 1 | JSON prompt tool: вход, выход, `permission_suggestions`, `updatedPermissions` (session и localSettings) | `echo a` затем `echo b`; политика Bash → allow + addRules `Bash(echo *)` | второй Bash не спрашивает; при `localSettings` появляется `.claude/settings.local.json` |
| 2a | `AskUserQuestion` через prompt tool | просим задать вопрос; политика — первый вариант | ответ модели содержит выбранный label; форма входа |
| 2b | `ExitPlanMode` через prompt tool, `setMode` | `--permission-mode plan`, план + одобрение с `setMode acceptEdits` | форма входа (`plan`); после одобрения Write проходит без вопроса или спрашивает |
| 3 | Image block в stdin | красный PNG + «какой цвет?» | «red» |
| 4 | SIGINT в `-p` stream-json | `sleep 30` → SIGINT после `tool_use` → второе сообщение | есть ли `result`, жив ли процесс, отвечает ли на второе |
| 5 | `--resume` из другой cwd | тур в A, resume в B | вспоминает кодовое слово; путь транскрипта |
| 6 | Сегменты текста и `--verbose` | «скажи X, вызови Bash, скажи Y»; с `--verbose` и без | порядок событий; есть ли `stream_event` без `--verbose` |
| 7 | `claude-agent-sdk.list_sessions()` без процесса | venv в scratchpad | видит сессии из 5 и терминальную сессию этого проекта |
| 9 | `--permission-prompts none` и `dontAsk` | тот же `echo` без prompt tool | что в `permission_denials` |

## Phase results

Прогон 2026-09-03, `claude` 2.1.259, модель haiku, ~$0.30 суммарно. Артефакты (events.jsonl,
mcp.log, summary.txt на эксперимент) — в scratchpad сессии, не коммитятся.

| # | Результат |
|---|---|
| 1 | Prompt tool получает `arguments={tool_name, input, tool_use_id}`, `_meta={claudecode/toolUseId, progressToken}`; **`permission_suggestions` нет**. Ответ text-content с JSON. `updatedPermissions` `session`: второй `mkdir` не спрошен. `localSettings`: создан `.claude/settings.local.json` с `Bash(mkdir *)`. `echo` до prompt tool не доходит (read-only набор). |
| 1-deny | `{"behavior":"deny","message":…}` → `tool_result{is_error:true, content:<message>}`; модель выполнила альтернативу из сообщения; `result.permission_denials` = 1. |
| 2a | `AskUserQuestion` пришёл в prompt tool с `input.questions[{question, header, options[{label, description}], multiSelect}]`; `updatedInput={questions, answers:{<q>: "Blue"}}` → финал «Blue». |
| 2b | В `--permission-mode plan` модель записала план в `~/.claude/plans/*.md` (разрешено само), вызвала `ExitPlanMode` с `input={plan, planFilePath}`; allow + `setMode acceptEdits (session)` → `Write hello.txt` прошёл без вопроса, файл создан. |
| 3 | Красный PNG base64 в `content[]` → «Red». |
| 4 | SIGINT через 2 с после `tool_use:Bash sleep 40`: `user[text "[Request interrupted by user]"]`, `tool_result{is_error}`, `result/error_during_execution` (`stop_reason: tool_use`, `is_error: true`), **процесс вышел с кодом 0**, второе stdin-сообщение не обработано. `--resume` той же сессии: модель помнит задание. |
| 5 | Тур в `sandbox`, `--resume` из `other_cwd` → «ZEBRA»; `init.cwd` = other_cwd; транскрипт остался в `projects/<sandbox>`; `--fork-session --name spike-fork` → новый `session_id`, контекст скопирован. |
| 6 | Без `--verbose`: `Error: When using --print, --output-format=stream-json requires --verbose`, exit 1. С `--verbose`: 27 stream-событий; порядок: `message_start` → `content_block_start:thinking` → `thinking_delta`… → `signature_delta` → **`assistant[thinking]`** → `content_block_stop` → `content_block_start:text` → `text_delta` → **`assistant[text]`** → `content_block_start:tool_use` → `input_json_delta`… → **`assistant[tool_use]`** → `message_delta/stop` → `user[tool_result]` → … → `result`. |
| 7 | `claude-agent-sdk` 0.2.152 `list_sessions(directory)` без процесса: видит spike-сессию и терминальную сессию этого репозитория (summary, custom_title, cwd, last_modified). |
| 9 | `--permission-prompts none` и `--permission-mode dontAsk`: событие `system/permission_denied {tool_name, tool_use_id, decision_reason_type: "asyncAgent", decision_reason, message}`, `tool_result{is_error}`, `result.permission_denials=[{tool_name, tool_use_id, tool_input}]`. |
| доп. | `init`: `permissionMode`, `slash_commands`, `agents`, `skills`, `capabilities`, `claude_code_version`, `apiKeySource`, `mcp_servers[{name,status}]`. `result`: `stop_reason`, `terminal_reason`, `modelUsage{model: {costUSD, contextWindow…}}`, `subagent_stats`. Прочие события: `system/status{status:"requesting"}`, `system/thinking_tokens`, `rate_limit_event{rate_limit_info.unifiedWindows.five_hour.utilization…}`. |

Отклонения от плана: эксперимент 8 (рендер draft) перенесён в smoke фазы 3; проверка resume
внутри контейнера — в фазу 1; `auto`-режим — в фазу 5.

## Manual smoke checklist

Нет — фаза без деплоя.

## Open questions

- Стоимость прогона: ~10 вызовов haiku, единицы центов.
