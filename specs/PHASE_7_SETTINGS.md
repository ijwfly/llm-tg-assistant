# PHASE_7_SETTINGS — настройки, персона, голос, расход

Status: all phases done — настройки на карточке, персона, голос, расход; tests green (189 passed); smoke — у пользователя

## Why

Модель, усилие, права и флаги показа сейчас задаются только конфигом или командой `/perm`.
PROJECT_SPEC 4.8–4.9 хочет карточку темы как пульт: переключатели прямо на ней, персона
(SOUL) и преамбула моста в системном промпте, голосовые ответы через внешний TTS, `/usage`
по месяцу и строка лимитов подписки.

## Verified facts

- `--append-system-prompt-file <file>` принимается CLI (spec 2.1); поддержка **двух** таких
  флагов не проверена → мост склеивает преамбулу и персону в один файл на спавн.
- `rate_limit_event.rate_limit_info.unifiedWindows.{five_hour,seven_day}.utilization` (spike,
  доп.) — форма для строки «Лимиты»; поля `resetsAt` считаем **assumed** и показываем, если есть.
- `system/init.model` — реальная модель процесса (после `--model`), пишется в `turns.model`.
- aiogram `SendVoice(chat_id, voice, caption, message_thread_id)`; outbox уже открывает `file://` для `voice`.
- На хосте есть `say` (macOS) и `ffmpeg`: `TTS_CMD` для smoke — `say -o {wav} --data-format=LEI16@22050 -f {text_file} && ffmpeg -y -loglevel error -i {wav} -c:a libopus {out}`.

## Decisions

| Вопрос | Решение |
|---|---|
| Карточка темы | Ряды: `Прервать` (если идёт ход) · `Новый контекст` `Стоп процесса` · `Права: prompt` `Модель: по умолчанию` `Усилие: по умолчанию` · `Сессии` `Ветка` · `Ещё` · `Обновить` `Скрыть` `Удалить тему`. Нажатие переключателя циклически меняет значение (права: `prompt → acceptEdits → plan → auto → dontAsk [→ bypass при ALLOW_BYPASS]`; модель: `по умолчанию → MODEL_CHOICES…`; усилие: `по умолчанию → low → medium → high → xhigh → max`), перезапускает процесс (контекст цел) и перерисовывает карточку на месте, без отдельного сообщения. |
| Страница «Ещё» | Та же карточка, текст тот же, вторая клавиатура: `Превью ответа: вкл/выкл`, `Размышления: вкл/выкл`, `Статистика хода: вкл/выкл`, `Голосом: вкл/выкл` (тема); `Голос = вопрос: вкл/выкл`, `Форвард = вопрос: вкл/выкл`, `Реакции: вкл/выкл` (пользователь); `Назад`. Значения темы — `topics.settings` (дефолт из `settings.*`), пользователя — `users.settings`. |
| Команды | `/model [имя\|default]`, `/effort [low\|medium\|high\|xhigh\|max\|default]`, `/soul [путь\|off\|default]`, `/voice [on\|off]`, `/usage`; без аргумента — текущее значение. `/perm` как раньше. |
| Системный промпт | `bridge_preamble.md` в корне репозитория (`BRIDGE_PREAMBLE_PATH` переопределяет) + персона (`topics.soul_path`: путь / `off` / NULL → `SOUL_PATH`, если файл есть) склеиваются в `INBOX_DIR/system/topic-<id>.md` при спавне → один `--append-system-prompt-file`. Правки файлов вступают в силу после перезапуска процесса. Путь персоны — внутри `WORK_ROOT` или `~/.config`, должен существовать. |
| Голосовой ответ | `voice` темы on + `TTS_CMD` → после финального текста хода: проза из всех сегментов (код, таблицы, разметка, ссылки выброшены), ≤ `TTS_MAX_CHARS` 900 по границе предложения, `TTS_CMD` с `{text_file}`, `{wav}`, `{out}` (OGG/Opus в `INBOX_DIR/out/voice-<turn>.ogg`), таймаут `TTS_TIMEOUT` 120 → `sendVoice` через outbox. Ошибка/пусто — молча (в лог). `/voice on` без `TTS_CMD` → `Синтез не настроен: задай TTS_CMD.` |
| `/usage` | Карточка за календарный месяц из `turns` (`cost_usd`, `usage.input_tokens/output_tokens`, новый столбец `model`): по темам, по моделям, итог; кнопка `Скрыть`. На подписке `cost_usd` есть в `result` (CLI считает), показываем как есть. |
| Лимиты | `RuntimeRegistry.rate_limit` — последний `rate_limit_info` любой темы; строка `Лимиты      5 ч: 25% · 7 дн: 10%` в `/status`, когда есть. |
| Настройки | `MODEL_CHOICES = ["sonnet", "opus", "haiku"]`, `EFFORT_CHOICES`, `SOUL_PATH`, `BRIDGE_PREAMBLE_PATH`, `TTS_CMD`, `TTS_TIMEOUT`, `TTS_MAX_CHARS`. |

## Design

- `app/render/keyboards.py` — `topic_card_kb(topic, user_settings, running, page)`; callback `set:<topic>:<key>` (цикл/тоггл), `page:<topic>:<more|main>`.
- `app/core/actions.py` — `cycle_setting`, `toggle_flag`, `set_model`, `set_effort`, `set_soul`, `set_voice`, `usage_card`; `topic_card(page)`.
- `app/core/prefs.py` — чтение флагов темы/пользователя с дефолтами из `settings`.
- `app/bridge/cli.py` — `system_prompt_file(topic)`; `app/bridge/preamble` → `bridge_preamble.md`.
- `app/render/tts.py` — `speakable(text)`; `app/ingest/tts.py`? нет — `app/core/voice.py`: `synthesize(text, out_path)`.
- `app/core/runtime.py` — флаги темы в live view/статистике, накопление прозы, голос после финала, `turns.model` из `init`, `rate_limit`.
- `app/store/migrations/0005_usage.sql` — `turns.model`; `TurnsRepo.month_usage`.

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Карточка с переключателями и страницей «Ещё», `/model`, `/effort`, флаги темы в рендере, персона + преамбула | ✅ |
| 2 | `/voice` + TTS, `/usage`, лимиты в `/status` | ✅ |
| 3 | Документация, живая проверка | ✅ (smoke — у пользователя) |

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_settings.py` | кнопка `Права` циклит и перерисовывает карточку, следующий спавн с новым режимом; `Модель`/`Усилие` → argv; `Ещё` → вторая клавиатура, тоггл `Превью ответа` пишет `topics.settings` и прогресс без хвоста; тоггл `Реакции` пишет `users.settings`; `Назад`; `/model sonnet`, `/model`, `/model default`; `/effort high`; `/soul <путь>` → `--append-system-prompt-file` с преамбулой и персоной, `/soul off` → только преамбула, плохой путь; `bypass` только при `ALLOW_BYPASS` |
| `e2e/test_voice.py` | `/voice on` без TTS → подсказка; с `TTS_CMD` → `sendVoice` после текста с прозой без кода; `/voice off`; ход без текста — без голоса |
| `e2e/test_usage.py` | два хода в двух темах → карточка по темам и моделям, `turns.model` из init; лимиты в `/status` после `rate_limit_event` |
| `unit/test_tts_text.py` | очистка: fences, таблицы, заголовки, ссылки, лимит по предложению |

## Phase results

- 189 тестов. Переключение с карточки не шлёт отдельного сообщения (`announce=False`), карточка
  перерисовывается на месте. `/usage` — из `turns`, без отдельной таблицы `usage` из PROJECT_SPEC 6.6
  (столбца `model` в `turns` достаточно). Лимиты берутся из последнего `rate_limit_event` любой темы.

## Manual smoke checklist

1. `/status` → `Модель: …` несколько раз → карточка меняется на месте, ответ следующего хода
   идёт нужной моделью (`/status` показывает модель из `init`).
2. `Ещё` → `Размышления: выкл` → в draft нет строки 🧠.
3. `/soul ~/.config/llm-tg-assistant/SOUL.md` с «отвечай как пират» → следующий ход в стиле.
4. `TTS_CMD` через `say`+`ffmpeg` в `settings_local.py`, `/voice on`, вопрос → голосовое после текста.
5. `/usage` после пары ходов.

## Open questions

- Два `--append-system-prompt-file` подряд — не проверено, поэтому склейка.
- `verbose_tools` — фаза 8.
