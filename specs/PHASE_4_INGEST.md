# PHASE_4_INGEST — входной конвейер: батчер, staging, медиа, голос

Status: all phases done — батчер, staging, медиа, голос, правки; tests green (106 passed)

## Why

Сейчас ходом становится только текст одного сообщения. Пользователь Telegram отправляет
альбомы, форварды, файлы, голосовые и правит сообщения. Эта фаза реализует PROJECT_SPEC 4.4:
всё, что пришло за короткое окно, — один ход; форварды и файлы без вопроса молча копятся и
уходят со следующим вопросом; фото модель видит как картинку; голос распознаётся.

## Verified facts

- Bot API: `getFile` ≤ 20 МБ; `photo[]` — размеры по возрастанию, последний самый большой;
  `forward_origin` (`MessageOriginUser|HiddenUser|Chat|Channel`), legacy-поля
  `forward_from`/`forward_from_chat`/`forward_sender_name`; `media_group_id` у элементов альбома;
  `setMessageReaction` — одна реакция бота из фиксированного набора (👀 есть).
- aiogram 3.31: `bot.download(file, destination)` = `getFile` + `session.stream_content`; `Command`
  фильтр читает и `text`, и `caption`; `Router.edited_message`.
- Image block в stream-json принимает base64 JPEG (spike 3).

## Decisions

| Вопрос | Решение |
|---|---|
| Батчер | `Batcher` в памяти: ключ — тема; скользящее окно `BATCH_WINDOW_MS` (300); флаш → сортировка по `message_id`; якорь — первое сообщение (reply-цитата). В ход элементы ложатся в фиксированном порядке: форварды → файлы → транскрипции → тексты, внутри группы по `message_id`. Команды не батчатся. |
| Классификация | `classify(message, user_settings)` → `prompt` / `staging` / `skip` по матрице 4.4.2. Батч — prompt, если есть хотя бы один prompt-элемент. |
| Staging | Таблица `staging_items(topic_id, kind, order_group, payload, tg_message_id)`; payload = текстовые блоки + пути картинок (base64 строится при потреблении). При prompt-ходе все элементы темы забираются в порядке `order_group` (0 форварды, 1 файлы, 2 транскрипции) и удаляются. `/new` очищает. Карточка показывает `Staging N`. |
| Медиа в ход | Фото: самый большой размер → `INBOX_DIR/<topic>/<YYYYMMDD>/photo_<msg>.jpg`, image block base64 (`image/jpeg`) + строка `[фото сохранено: <путь>]`. Документ: `[файл <имя>: <путь>] (<размер>)`. Голос/аудио/кружок: скачать; `TRANSCRIBE_CMD` (`{file}`, `{wav}`; stdout → текст; таймаут `TRANSCRIBE_TIMEOUT`) → текст + эхо `🎤 _текст_` reply'ем на голосовое; иначе `[голосовое: <путь>]`. Видео: только подпись. |
| Форварды | `[переслано от <Имя Фамилия (@username)> | <скрытое имя> | Chat name "<title>"]` первой строкой; фото форварда сохраняет image block; forward никогда не reply. `forward_as_prompt=on` → обычное сообщение без префикса. |
| Правка сообщения | `edited_message` → prompt с первой строкой `[правка предыдущего сообщения]`, в чат `✏️ Вижу правку — отвечаю на неё.` |
| Лимиты | Документ/фото > `FILE_MAX_MB` (20), голос > `VOICE_MAX_MB` (25) → reply `⚠️ …`, элемент пропускается, остальное идёт. |
| Реакции | `REACTIONS` + `users.settings.reactions` (on): staged → 👀 на каждое сообщение; ход упал/ошибка → 👾 на якорь. Через outbox (`SetMessageReaction`), ошибки — permanent. |
| Имена файлов | Буквы (в т.ч. кириллица), цифры, `_ . -`; остальное → `_`; коллизия → `_1`, `_2`. |
| Inbox | `inbox_files(topic_id, path, tg_file_id, kind, size)`; `/files` — последние 10 файлов темы; чистка старше `INBOX_TTL_DAYS` (7) при старте и каждые 6 ч. |
| Настройки пользователя | `users.settings` jsonb: `forward_as_prompt` (off), `voice_as_prompt` (on), `reactions` (on). UI-переключатели — фаза 7. |

## Deliverables

- `app/store/migrations/0003_ingest.sql`; `StagingRepo`, `InboxRepo`, `UsersRepo.settings()`
- `app/ingest/{classify,files,transcribe,batcher,pipeline}.py`
- `app/transport/handlers.py`: медиа/форварды/правки → батчер; `/files`; `/new` чистит staging; карточка со staging
- настройки: `BATCH_WINDOW_MS`, `TRANSCRIBE_CMD`, `TRANSCRIBE_TIMEOUT`, `INBOX_TTL_DAYS`, `REACTIONS`, `FILE_MAX_MB`, `VOICE_MAX_MB`
- тесты ниже; `E2E_TESTS.md`, `CHANGELOG.md`, `CLAUDE.md`

## Tests

| Файл | Сценарии |
|---|---|
| `e2e/test_ingest.py` | альбом из двух фото с подписью → один ход с двумя image block и текстом, файлы в inbox; текст+фото+голос за окно → один ход по `message_id`; форвард без вопроса → staging, 👀, хода нет; вопрос после → ход с атрибуцией и текстом форварда, staging пуст; документ без подписи → staging; с подписью → prompt с `[файл …]`; голос с `TRANSCRIBE_CMD` → эхо 🎤 и текст; без команды → `[голосовое: …]`; `voice_as_prompt=off` → staging; правка → ход с пометкой и `✏️`; файл > лимита → предупреждение, вопрос идёт; `/new` чистит staging; карточка показывает `Staging`; `/files`; `forward_as_prompt=on` |
| `unit/test_classify.py` | матрица классификации, атрибуция форварда, санитайзер имён, коллизии |
| `unit/test_inbox_cleanup.py` | удаление старых файлов и строк |

## Phase results

- Всё из Deliverables; `bash scripts/test.sh` — 106 passed (~30 с).
- Сериализация outbox: `exclude_defaults` выкидывал дискриминатор `type: "emoji"` у реакции;
  заменена на `dump_method` (убирает только `Default`-сентинели aiogram).
- Тесты очереди ходов теперь разносят сообщения по времени больше окна батчера.
- Реакция 👾 при ошибке хода отложена (только 👀 на staging).
- Даунскейла фото нет; image block пропускается, если файл больше 5 МБ.
- Живая проверка: Telegram отправляет комментарий к форвардам раньше самих форвардов, и вопрос
  оказывался перед контекстом. Теперь и внутри батча порядок фиксированный: форварды → файлы →
  транскрипции → тексты, внутри группы по `message_id` (как в tg_ux §1).

## Manual smoke checklist

1. Альбом из 2 фото с подписью «что на картинках?» — один ответ про обе.
2. Переслать 3 сообщения без вопроса — реакции 👀, тишина; затем «о чём это?» — ответ учитывает все.
3. Документ без подписи → 👀; «прочитай файл» → модель читает по пути из inbox.
4. Голосовое → эхо 🎤 (если настроен `TRANSCRIBE_CMD`) и ответ.
5. Правка своего сообщения → `✏️` и новый ответ.

## Open questions

- Даунскейл больших фото (PIL) — пока не нужен: Telegram отдаёт ≤ 1280 px.
