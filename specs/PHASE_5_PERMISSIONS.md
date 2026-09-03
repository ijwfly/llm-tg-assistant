# PHASE_5_PERMISSIONS — разрешения, вопросы и планы кнопками

Status: all phases done — разрешения, вопросы и планы кнопками; tests green (143 passed); живая проверка — smoke ниже

## Why

Сейчас в режиме `prompt` всё, что Claude Code хотел бы спросить, отклоняется молча (`🔒` в
конце хода). Эта фаза реализует PROJECT_SPEC 4.6–4.7: запрос разрешения приходит карточкой с
кнопками `✅ ❌ 🔓 Всегда ✏️`, вопросы модели (`AskUserQuestion`) — карточками с вариантами,
план (`ExitPlanMode`) — карточкой с одобрением. Мост становится «prompt tool» Claude Code
через свой MCP-сервер.

## Verified facts

- Spike 1 (`specs/PHASE_0_SPIKE.md`): prompt tool получает `arguments={tool_name, input,
  tool_use_id}`, без `permission_suggestions`; ответ — text-content с JSON
  `{"behavior":"allow","updatedInput":…,"updatedPermissions":[…]}` или
  `{"behavior":"deny","message":…}`; `updatedPermissions` с `destination: localSettings`
  пишет `.claude/settings.local.json`; deny с `message` → `tool_result{is_error}` и модель
  следует подсказке.
- Spike 2a/2b: `AskUserQuestion` приходит с `input.questions[{question, header,
  options[{label, description}], multiSelect}]`, ответ `updatedInput={questions, answers:{<q>:
  label | [labels]}}`; `ExitPlanMode` приходит с `input={plan, planFilePath}`, allow +
  `updatedPermissions=[{type: setMode, mode: acceptEdits, destination: session}]` переключает
  режим живого процесса.
- `--mcp-config` принимает JSON-строку (docs: «JSON files or strings»); fake `claude` тоже.
- aiogram 3.31: `EditMessageText.rich_message` есть — карточку с fences можно править на месте.
- Unix-сокет: длина пути ≤ 104 байта на macOS — тестовый путь берётся из `tempfile`, не из
  `tmp_path`.
- **Assumed** (smoke не наблюдал): в `auto` режиме спорные вызовы доходят до prompt tool; в проверке `auto` разрешил Write/rm сам.

## Decisions

| Вопрос | Решение |
|---|---|
| MCP-сервер | `app/bridge/mcp_server.py`, только stdlib, запускается как файл (`sys.executable <path>`), чтобы не зависеть от `sys.path`/cwd темы. Инструмент один: `approve`. На `tools/call` — одна JSON-строка в unix-сокет `TGBRIDGE_SOCKET` `{token, tool, tool_use_id, args}`, одна строка ответа. Таймаут `TGBRIDGE_TIMEOUT` (= `QUESTION_TIMEOUT_SECS + 30`); при недоступности демона/обрыве — `deny` с причиной. |
| Сокет демона | `app/bridge/socket_server.py`, `asyncio.start_unix_server` на `settings.BRIDGE_SOCKET`; стартует/гасится вместе с `App`. Запрос по `token` попадает в `PromptService.handle`. |
| Токен | На каждый спавн процесса темы — `secrets.token_urlsafe(12)`; `RuntimeRegistry`/`PromptService` держат `token → TopicRuntime`; снимается при остановке процесса. Чужой/устаревший токен → deny. |
| Когда включён prompt tool | Режимы `prompt`, `acceptEdits`, `plan`, `auto`: argv получает `--permission-prompt-tool mcp__tgbridge__approve --mcp-config <json>`. `dontAsk`/`bypass` — без него. `--strict-mcp-config` не ставим: MCP пользователя из его настроек остаются. |
| Состояние запроса | `PromptService` в памяти (`PendingPrompt`: future, вид, вопрос-индекс, выбранные варианты, ожидание текста) + строка `pending_prompts` в БД (учёт, устаревшие кнопки после рестарта). При старте демона все `pending` → `stale`. |
| Карточка разрешения | Rich-markdown по таблице 4.6.2 (`app/render/cards.py`): Bash — ` ```bash ` + description; Edit — путь + ` ```diff ` (difflib, ≤ `PERMISSION_DIFF_LINES` 60); Write — путь, размер, первые 40 строк или diff с существующим файлом; NotebookEdit — путь, ячейка, содержимое; Read/Grep/Glob/WebFetch/WebSearch — одна строка; прочие — ` ```json ` ≤ 700 символов, значения ключей `token|secret|password|key|authorization` замаскированы. Кнопки: `✅ Разрешить` `❌ Отклонить` / `🔓 Всегда: <правило>` (если есть) / `✏️ Отклонить и объяснить`. |
| Ответы карточки | Нажатие → правка карточки: кнопки убраны, хвост `✅ разрешено` / `❌ отказано` / `❌ отказано: «текст»` / `🔓 разрешено, и больше не спрошу: <правило>` / `⌛ без ответа — отклонено` / `🛑 ход прерван`. Deny-сообщения модели на английском: `User denied this action via Telegram.`, `User denied: <text>`, `User did not answer within N minutes.`, `Turn cancelled by the user.` |
| «Всегда» | Правило строит `app/bridge/rules.py` по таблице 4.6.3; ответ `updatedPermissions=[{type: addRules, behavior: allow, destination: localSettings, rules: [{toolName, ruleContent?}]}]`; мост пишет `topic_rules`. `/perm` показывает правила темы; `/perm forget` удаляет их из `.claude/settings.local.json` (ищет от cwd вверх до `WORK_ROOT`) и из `topic_rules`. |
| Ожидание текста | «Отклонить и объяснить», «Свой ответ», «Доработать план» переводят тему в ожидание: следующее текстовое сообщение темы (не команда) уходит ответом, а не ходом; перехват в `handlers.any_message` до батчера через `PromptService.consume_text`. Карточка дописывается `→ текст`. |
| AskUserQuestion | Карточка на вопрос последовательно: `❓ <header> (i/n)` + текст; кнопки — по варианту (`label — description` ≤ 60), для `multiSelect` тоггл `☐/☑` + `Готово`, последняя `✍ Свой ответ`. Ответ: `updatedInput={questions, answers}`; свободный текст на вопрос без вариантов/своим ответом — как строка answers. Таймаут `QUESTION_TIMEOUT_SECS` (30 мин) → deny `User did not answer…`. |
| ExitPlanMode | `📋 План готов` + markdown плана через `send_markdown` (кнопки на последнем чанке): `✅ Выполнять (правки без вопросов)` → allow + `setMode acceptEdits` + `topics.permission_mode=acceptEdits`; `✅ Выполнять, спрашивать про правки` → allow + `setMode default` + `permission_mode=prompt`; `✏️ Доработать` → ожидание текста → deny с текстом. Режим темы в БД меняется, чтобы следующий спавн (после простоя) не вернулся в `plan`. Переименование темы по плану — фаза 6. |
| Индикатор | `progress.waiting` = `🔐 жду разрешения (Bash)` / `❓ жду ответа` / `📋 жду решения по плану`; typing не шлётся, пока ждём; карточка `/status` показывает ожидание. |
| Отмена и конец хода | `cancel()` и конец хода (любой) резолвят висящие запросы темы как deny (`Turn cancelled…`) и правят их карточки; остановка процесса снимает токен. |
| Отклонения без вопроса | Текст `🔒` теперь объясняет режим (`dontAsk`/правила), кнопки прежние. |
| Настройки | `BRIDGE_SOCKET` (env, default `/tmp/tgbridge.sock`; compose — `/data/bridge.sock`), `PERMISSION_TIMEOUT_SECS` 600, `QUESTION_TIMEOUT_SECS` 1800, `PERMISSION_DIFF_LINES` 60. |
| Outbox | `send_markdown(reply_markup=)` вешает кнопки на последний чанк; `edit_markdown` — rich-правка с fallback в plain при отказе Telegram. |

## Design

- `app/bridge/mcp_server.py` — stdio JSON-RPC (`initialize`, `tools/list`, `tools/call`, `ping`), сокет-клиент.
- `app/bridge/socket_server.py` — `BridgeSocket(app)`: `start()`, `stop()`, обработчик соединения → `app.prompts.handle(request)`.
- `app/bridge/rules.py` — `always_rule(tool_name, input) -> Rule | None`, `rule_text(rule)`, `forget_rules(cwd, rules) -> int`.
- `app/core/prompts.py` — `PromptService`: `register/unregister(token, runtime)`, `handle(req)`, `run_permission/run_question/run_plan`, callbacks `permission(prompt_id, decision)`, `question_option`, `question_done`, `plan(decision)`, `await_text`, `consume_text(topic, message)`, `abandon(topic_id, reason)`, таймауты, правка карточек.
- `app/render/cards.py` — `permission_card`, `question_card`, `plan_card`, `mask_secrets`, `diff_block`.
- `app/render/keyboards.py` — `permission_kb`, `question_kb`, `plan_kb`; callback-данные `pa|pd|pw|pc:<topic>:<prompt>`, `qo:<topic>:<prompt>:<opt>`, `qd|qc:<topic>:<prompt>`, `pl:<topic>:<prompt>:<accept|ask|rework>`.
- `app/transport/callbacks.py` — маршрутизация новых действий; `handlers.any_message` — перехват ожидаемого текста; `/perm forget`.
- `app/core/runtime.py` — токен и argv с prompt tool, `waiting` в typing/status, резолв висящих запросов при отмене/конце хода.
- `app/store/migrations/0004_prompts.sql` — `pending_prompts`, `topic_rules`; `PromptsRepo`, `RulesRepo`.
- fake `claude`: шаг `prompt_tool` уже есть; `tests/support/fake_claude.py` получает `prompt_tool(...)` и `decisions()`.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | MCP-сервер, сокет, `PromptService`, карточка разрешения (allow/deny/always/comment/timeout/stale/cancel), правила, `/perm` с правилами и `forget`, индикатор | ✅ |
| 2 | `AskUserQuestion`: карточки, multiSelect, свой ответ, таймаут | ✅ |
| 3 | `ExitPlanMode`: карточка плана, setMode, доработка | ✅ |
| 4 | Документация: `E2E_TESTS.md`, `CHANGELOG.md`, `CLAUDE.md`, `PROJECT_SPEC.md`; живая проверка | ✅ (smoke — у пользователя) |

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_permissions.py` | карточка Bash с командой и кнопками, индикатор `🔐 жду разрешения (Bash)`; `✅` → allow с `updatedInput`, карточка `✅ разрешено` без кнопок; `❌` → deny с сообщением; `🔓 Всегда` → `updatedPermissions localSettings` + `topic_rules`; `✏️` → следующий текст = message отказа, ход не создан; таймаут → deny и `⌛`; повторное нажатие → тост «неактуально»; `🛑` во время запроса → deny и `🛑 ход прерван`; карточка Edit с diff; Write нового файла; чужой инструмент с маскированием; `dontAsk` без prompt tool в argv; `/perm` показывает правило, `/perm forget` чистит файл и таблицу; рестарт демона помечает запросы `stale` |
| `e2e/test_questions.py` | один вопрос → кнопка → `answers`; multiSelect тоггл и `Готово`; два вопроса подряд; `✍ Свой ответ` → текст; таймаут |
| `e2e/test_plans.py` | план → `✅ без вопросов` → allow + `setMode acceptEdits`, режим темы обновлён; `спрашивать про правки` → `setMode default`; `✏️ Доработать` → deny с текстом |
| `unit/test_rules.py` | матрица «Всегда», `forget_rules` |
| `unit/test_cards.py` | рендер по инструментам, маскирование, обрезка diff |
| `unit/test_mcp_server.py` | initialize/tools/list; сокета нет → deny с причиной; ответ демона проксируется |

## Phase results

- **Фаза 1**: 135 тестов. Fake `claude` реально запускает `mcp_server.py` из `--mcp-config` и
  ждёт решения по сокету — путь «CLI → MCP → сокет → карточка → кнопка → решение» покрыт целиком.
  `PromptService` заодно реализует вопросы и планы (общий код); их тесты — фазы 2–3. Сокет-обработчик
  следит за EOF от MCP-клиента: если `claude` умер, запрос закрывается как прерванный.
- **Фазы 2–3**: 143 теста; код вопросов/планов был в `PromptService` с фазы 1, добавлены
  `e2e/test_questions.py`, `e2e/test_plans.py`. Отклонение от спеки 4.7.1: свободный ответ
  кладётся в `answers[<вопрос>]` строкой, отдельного поля `response` нет (spike показал, что
  модель читает `answers`).
- **Фаза 4**: документация; `docker-compose.yml` задаёт `BRIDGE_SOCKET=/data/bridge.sock`.
- **Живая проверка** (2026-09-03, @AtlasHarbot): карточка Write → `✅` → файл создан; вопрос
  `AskUserQuestion` кнопками → ответ учтён; в логе ни одной ошибки. В режиме `auto` Write и
  `rm` только что созданных файлов прошли без карточки — классификатор CLI разрешил сам, до
  prompt tool не дошло. Факт «auto доводит спорное до prompt tool» остаётся не наблюдённым
  (не опровергнут); при необходимости кнопок — `prompt`.

## Manual smoke checklist

1. `/perm prompt`, «создай файл hello.txt» → карточка Write с содержимым → `✅` → файл есть.
2. «выполни `git status`» → карточка Bash → `🔓 Всегда: Bash(git status *)` → в
   `.claude/settings.local.json` появилось правило; повтор не спрашивает; `/perm` его показывает;
   `/perm forget` убирает.
3. `❌ Отклонить и объяснить` → текст → модель делает иначе.
4. Не отвечать `PERMISSION_TIMEOUT_SECS` (поставить 30 с локально) → `⌛`, ход продолжается.
5. «спроси меня, какой формат» → карточка вопроса → вариант → ответ учитывает выбор; свой ответ.
6. `/perm plan`, задача → карточка плана → `✅ Выполнять (правки без вопросов)` → правки идут без
   карточек; `/status` показывает `acceptEdits`.
7. `/perm auto`: «удали файл через rm» — доходит ли до карточки (закрыть assumed-факт).
8. Кнопка старой карточки после рестарта бота → тост.

## Open questions

- Переименование темы/сессии по заголовку плана — вместе с `/rename` в фазе 6.
- Параллельные tool-вызовы: MCP-сервер обрабатывает запросы по одному, карточки идут
  последовательно; если CLI шлёт их конкурентно, вторая ждёт первую — приемлемо.
