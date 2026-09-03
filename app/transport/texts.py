"""All user-facing strings of the bot live here (Russian)."""
from app.render.markdown import format_duration

def help(user_id: int, chat_id: int, thread_id: int | None) -> str:
    return (
        "Я управляю сессиями Claude Code на сервере. Тема = папка, в ней — текущая сессия.\n\n"
        "Просто пиши — это ход Claude Code. Reply на сообщение цитирует его. Файлы и голосовые тоже понимаю.\n\n"
        "Почти всё — кнопками на карточке темы (/status): прервать, повторить, новый контекст, стоп процесса, "
        "права, модель, усилие, сессии, ветка, удалить тему; страница «Ещё» — превью, размышления, статистика, "
        "голос, реакции, правила «Всегда».\n\n"
        "/status — карточка темы\n"
        "/new — новый контекст (старая сессия остаётся в «Сессиях» на карточке)\n"
        "/project <алиас|путь> — тема под папку; /project new <имя> — новая папка\n"
        "/rename <имя> — переименовать тему и сессию\n"
        "/soul [путь|off|default] — персона в системном промпте\n"
        "/files — последние файлы темы\n"
        "/usage — расход за месяц\n"
        "/help — эта справка\n\n"
        "Остальные /команды (/compact, /cost, /context…) уходят в Claude Code как есть.\n\n"
        f"Твой id: {user_id} · чат: {chat_id} · тема: {thread_id if thread_id is not None else '—'}"
    )


NOT_AUTHORIZED = "Not authorized"
TOPICS_EMPTY = "Пока пусто."

STARTUP = "🌅 Я на месте. Бот @{username}, режим {mode}, тем: {topics}, версия {version}"
SHUTDOWN = "⏹ Останавливаюсь."

NEW_CONTEXT = "🆕 Новый контекст. Прошлая сессия сохранена на диске."
PROCESS_STOPPED = "⏸ Процесс остановлен, контекст сохранён."
CANCELLED = "🛑 Прервано."
NOTHING_TO_CANCEL = "Нечего прерывать."
NOTHING_TO_RETRY = "Нечего повторять — в этой теме ещё не было хода."
QUEUE_HINT = "🕐 Дописываю текущий ход — это следующим."
QUEUE_FULL = "⚠️ Очередь полна, повтори позже."
CD_OK = "📁 {path}\nКонтекст начат заново — сессия привязана к директории."
CD_NO_DIR = "⚠️ нет такой директории: {path}"
CD_OUTSIDE = "⚠️ {path} лежит вне рабочего корня {root}."
CD_USAGE = "Куда? /cd <путь> или /go <алиас>."
GO_EMPTY = "Алиасов пока нет: добавь PROJECTS = {{\"app\": \"/work/app\"}} в settings_local.py."
GO_UNKNOWN = "Нет алиаса {alias}. Список — /go без аргумента."

TURN_NO_TEXT = "✔️ Готово — в ответе не было ни слова текста."
TURN_ERROR = "⚠️ Ход завершился с ошибкой: {error}"
TURN_LIMIT = "⏹ Достигнут лимит {what}. Контекст цел — продолжай или /retry."
DENIED = "🔒 Отклонено без спроса: {tools}\nРежим темы не спрашивает (dontAsk или правило deny); /perm prompt вернёт кнопки."
TURN_TIMEOUT = "⏱ Ход шёл дольше лимита и был прерван. Контекст сохранён."
DAEMON_STOPPED = "⏹ Демон остановлен посреди хода. Контекст цел — /retry повторит."
COMPACTED = "🧹 Контекст сжат: было {pre_tokens} токенов."
TURN_INTERNAL_ERROR = "💥 Внутренняя ошибка моста при обработке хода. Подробности в логе; /retry повторит."
ANSWER_IN_FILE = "Ответ целиком — в файле."
FILE_TOO_BIG = "⚠️ Файл больше {limit} МБ, Telegram не отдаёт такие ботам. Пропускаю его, остальное ушло."
VOICE_TOO_BIG = "⚠️ Голосовое больше {limit} МБ. Пропускаю его."
EDIT_SEEN = "✏️ Вижу правку — отвечаю на неё."
FILES_EMPTY = "В этой теме файлов пока нет."

SESSIONS_EMPTY = "Внутри {root} сессий Claude Code пока нет."
SESSIONS_OUTSIDE = "ещё {n} вне {root} — бот туда не ходит"
SESSION_TOPIC_HELLO = "Продолжаю сессию {short} · «{title}»\nПапка: {cwd}\nПиши сюда."
PROJECT_NEW_CREATED = "📁 Создала папку {path}."
PROJECT_NEW_BAD_NAME = "Имя папки — одно слово без / и .. : /project new my-app"
PROJECT_NEW_USAGE = "Как назвать? /project new <имя> создаст папку в {dir}."
SESSION_NOT_FOUND = "Не нашла сессию «{query}». /sessions покажет, что есть."
SESSION_AMBIGUOUS = "Под «{query}» подходят несколько сессий:\n{rows}\nУточни id."
RESUMED = "🔗 Подключилась к сессии {short} · «{title}»\nДиректория: {cwd}"
RESUMED_CWD_KEPT = "⚠️ Директория сессии {cwd} недоступна, тема остаётся в {kept}."
RESUME_USAGE = "Какую? /resume <id | префикс ≥ 4 | имя>. Список — /sessions."
BRANCH_OPENED = "🌿 Ветка «{name}» открыта."
BRANCH_HELLO = "🌿 Продолжаю с копии контекста сессии {short}. Пиши сюда."
PROJECT_OPENED = "✅ Тема «{name}» открыта."
PROJECT_HELLO = "📁 {path}\nТема готова, контекст чистый. Пиши сюда."
PROJECT_USAGE = "Куда? /project <алиас | путь> — тема под существующую папку; /project new <имя> — новая папка, сессия и тема."
TOPIC_CREATE_FAILED = "⚠️ Не могу создать тему: {reason}. Нужен чат с включёнными темами (форум или личка с topics) и право «Управление темами»."
RENAMED = "✏️ {name}"
DELETE_CONFIRM = "Удалить тему «{name}» вместе с сообщениями? Сессия Claude Code останется на диске, её видно в /sessions."
DELETE_NOT_A_TOPIC = "Это не тема, а сам чат — удалять нечего."
DELETE_FAILED = "⚠️ Не могу удалить тему: {reason}"
TOAST_DELETED = "Тема удалена"
RENAME_USAGE = "Как назвать? /rename <имя>."
TOAST_BRANCHED = "Ветка открыта"
TOAST_RESUMED = "Подключилась"

MODEL_SET = "🤖 Модель: {model}. Процесс перезапустится на следующем ходе, контекст остаётся."
MODEL_INFO = "Модель темы: {model}. /model <имя|default> — сменить; варианты: {choices}."
EFFORT_SET = "🎚 Усилие: {effort}. Процесс перезапустится на следующем ходе, контекст остаётся."
EFFORT_INFO = "Усилие темы: {effort}. /effort <low|medium|high|xhigh|max|default>."
EFFORT_UNKNOWN = "Не знаю усилие {effort}. Варианты: low, medium, high, xhigh, max, default."
SOUL_SET = "🎭 Характер: {path}. Вступит в силу со следующего процесса."
SOUL_OFF = "🎭 Характер выключен для этой темы."
SOUL_DEFAULT = "🎭 Характер: из конфига ({path})."
SOUL_INFO = "Характер темы: {path}. /soul <путь|off|default>."
SOUL_NO_FILE = "⚠️ Нет такого файла: {path}. Путь должен быть внутри {root} или ~/.config."
VOICE_ON = "🔊 Голосом: после текста придёт голосовое."
VOICE_OFF = "🔇 Только текст."
VOICE_INFO = "Голосовые ответы: {state}. /voice on|off."
TTS_NOT_CONFIGURED = "Синтез не настроен: задай TTS_CMD в settings_local.py."
TOAST_SWITCHED = "Переключено"

PERM_SET = "🔐 Права: {mode}. Процесс перезапустится на следующем ходе, контекст остаётся."
PERM_FORGOT = "Забыла {n} правил. Снова буду спрашивать."
PERM_NOTHING_TO_FORGET = "В этой теме я правил не добавляла."

# prompts (permissions, questions, plans)
PERM_ALLOWED = "✅ разрешено"
PERM_DENIED = "❌ отказано"
PERM_DENIED_WITH = "❌ отказано: «{text}»"
PERM_ALWAYS = "🔓 разрешено, и больше не спрошу: {rule}"
PERM_TIMEOUT = "⌛ без ответа — отклонено"
PERM_CANCELLED = "🛑 ход прерван"
PERM_ASK_COMMENT = "✏️ Напиши следующим сообщением, что сделать вместо этого."
QUESTION_ASK_CUSTOM = "✍ Напиши ответ следующим сообщением."
QUESTION_ANSWERED = "→ {answer}"
PLAN_ACCEPTED = "✅ выполняю, правки без вопросов"
PLAN_ACCEPTED_ASK = "✅ выполняю, про правки буду спрашивать"
PLAN_REWORK = "✏️ Напиши следующим сообщением, что поправить в плане."
PLAN_REWORKED = "✏️ на доработку: «{text}»"
WAITING_PERMISSION = "🔐 жду разрешения ({tool})"
WAITING_QUESTION = "❓ жду ответа"
WAITING_PLAN = "📋 жду решения по плану"
TOAST_PROMPT_STALE = "Запрос уже неактуален"
TOAST_ALLOWED = "Разрешено"
TOAST_DENIED = "Отклонено"
TOAST_ALWAYS = "Разрешено навсегда"
TOAST_WRITE_NEXT = "Жду твоё сообщение"
TOAST_CHOSEN = "Принято"

# what the model sees on a deny (English: it is the tool result)
DENY_MSG_USER = "User denied this action via Telegram."
DENY_MSG_COMMENT = "User denied: {text}"
DENY_MSG_TIMEOUT = "User did not answer within {minutes} minutes."
DENY_MSG_CANCELLED = "Turn cancelled by the user."
DENY_MSG_NO_TURN = "No active Telegram turn for this session."
DENY_MSG_PLAN_REWORK = "User asked to rework the plan: {text}"
PERM_UNKNOWN = "Не знаю режим {mode}. Варианты: prompt, acceptEdits, plan, auto, dontAsk" + ", bypass (если разрешён)."

TOAST_NEW = "Новый контекст"
TOAST_STOPPED = "Процесс остановлен"
TOAST_CANCELLING = "Прерываю…"
TOAST_QUEUED = "В очереди"
TOAST_SENT = "Отправлено"
TOAST_REFRESHED = "Обновлено"
TOAST_STALE = "Уже неактуально"
TOAST_FAILED = "Не получилось, смотри лог"


def perm_info(mode: str | None, topic_rules: list[str] = (), local_rules: list[str] = ()) -> str:
    modes = ["prompt", "acceptEdits", "plan", "auto", "dontAsk", "bypass"]
    rows = [f"{'← ' if m == (mode or 'prompt') else '   '}{m}" for m in modes]
    text = "Права темы:\n" + "\n".join(rows) + "\n\n/perm <режим> — сменить; /perm default — из конфига."
    if topic_rules:
        text += "\n\nРазрешила по кнопке «Всегда»:\n" + "\n".join(f"• {r}" for r in topic_rules)
        text += "\n/perm forget — забыть их."
    others = [r for r in local_rules if r not in set(topic_rules)]
    if others:
        text += "\n\nДругие allow-правила проекта:\n" + "\n".join(f"• {r}" for r in others[:20])
    return text


def crash(code: int | None, stderr_tail: str) -> str:
    text = f"💥 Процесс claude завершился (код {code})."
    if stderr_tail:
        text += f"\n```\n{stderr_tail[:1500]}\n```"
    return text + "\nКонтекст сохранён — /retry повторит ход."


def turn_stats(duration_ms: int | None, cost: float | None, steps: int | None) -> str:
    parts = [format_duration(duration_ms)]
    if cost is not None:
        parts.append(f"${cost:.2f}")
    if steps is not None:
        parts.append(f"{steps} шагов")
    return "_" + " · ".join(parts) + "_"


def whoami(user_id: int, chat_id: int, thread_id: int | None) -> str:
    return f"Твой id: {user_id}\nЧат: {chat_id}\nТема: {thread_id if thread_id is not None else '—'}"


def go_list(projects: dict[str, str]) -> str:
    return "Куда идём:\n" + "\n".join(f"/go {alias} — {path}" for alias, path in projects.items())


def sessions_card(root: str, rows: list[tuple[str, str, str, str, str]], outside: int = 0) -> str:
    """rows: (folder relative to root, short id, ago, title, where)."""
    if not rows:
        text = SESSIONS_EMPTY.format(root=root)
    else:
        lines = [f"Сессии Claude Code в {root}:"]
        for folder, short, when, title, where in rows:
            line = f"▸ {folder} · {short} · {when} · «{title[:60]}»"
            lines.append(line + (f" · {where}" if where else ""))
        text = "\n".join(lines)
    if outside:
        text += "\n" + SESSIONS_OUTSIDE.format(n=outside, root=root)
    return text


def files_list(rows: list[dict]) -> str:
    if not rows:
        return FILES_EMPTY
    return "Последние файлы темы:\n" + "\n".join(f"{r['kind']}: {r['path']}" for r in rows)


def _tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def usage_card(rows: list[dict], month: str) -> str:
    if not rows:
        return f"За {month} ходов ещё не было."
    by_topic: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total = {"turns": 0, "cost": 0.0, "inp": 0, "out": 0}
    for r in rows:
        for bucket, key in ((by_topic, r["topic"]), (by_model, r["model"])):
            acc = bucket.setdefault(key, {"turns": 0, "cost": 0.0, "inp": 0, "out": 0})
            acc["turns"] += r["turns"]; acc["cost"] += float(r["cost"]); acc["inp"] += r["input_tokens"]; acc["out"] += r["output_tokens"]
        total["turns"] += r["turns"]; total["cost"] += float(r["cost"]); total["inp"] += r["input_tokens"]; total["out"] += r["output_tokens"]

    def line(name, a):
        return f"{name}: {a['turns']} ходов · ${a['cost']:.2f} · {_tokens(a['inp'])} in / {_tokens(a['out'])} out"

    lines = [f"Расход за {month}", "", "По темам:"]
    lines += [line(k, v) for k, v in sorted(by_topic.items(), key=lambda kv: -kv[1]["cost"])]
    lines += ["", "По моделям:"]
    lines += [line(k, v) for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["cost"])]
    lines += ["", line("Итого", total)]
    return "\n".join(lines)


def limits_line(info: dict | None) -> str | None:
    windows = (info or {}).get("unifiedWindows") or {}
    names = {"five_hour": "5 ч", "seven_day": "7 дн"}
    parts = []
    for key, label in names.items():
        w = windows.get(key) or {}
        if w.get("utilization") is not None:
            parts.append(f"{label}: {round(float(w['utilization']) * 100)}%")
    return " · ".join(parts) if parts else None


def status(topic: dict, rt: dict | None, staging: int = 0, session_title: str | None = None,
           rate_limit: dict | None = None) -> str:
    thread = topic["thread_id"] if topic["thread_id"] is not None else "—"
    rt = rt or {}
    proc = rt.get("process")
    turn = rt.get("turn")
    lines = [
        f"Тема         {topic.get('title') or '—'} ({topic['chat_id']}:{thread})",
        f"Сессия       {topic['session_id'] or 'ещё нет'}" + (f" · «{session_title[:60]}»" if session_title else ""),
        f"Директория   {topic['cwd']}",
        f"Модель       {topic['model'] or 'по умолчанию'}   Усилие  {topic['effort'] or 'по умолчанию'}",
        f"Права        {topic['permission_mode'] or 'по умолчанию'}",
        f"Процесс      {'живой, ' + format_duration(int(proc * 1000)) if proc is not None else 'спит'}",
        f"Ход          {'идёт ' + format_duration(int(turn * 1000)) if turn is not None else 'нет'}"
        + (f" · в очереди {rt['queued']}" if rt.get("queued") else "")
        + (f" · {rt['waiting']}" if rt.get("waiting") else ""),
    ]
    if staging:
        lines.append(f"Staging      {staging} (уйдёт со следующим вопросом)")
    last = rt.get("last")
    if last:
        lines.append("Последний    " + turn_stats(last.get("duration_ms"), last.get("cost_usd"), last.get("num_turns")).strip("_"))
    limits = limits_line(rate_limit)
    if limits:
        lines.append(f"Лимиты       {limits}")
    return "\n".join(lines)


def topics_list(topics: list[dict], runtime_states: dict[int, dict]) -> str:
    if not topics:
        return TOPICS_EMPTY
    rows = []
    for t in topics:
        thread = t["thread_id"] if t["thread_id"] is not None else "—"
        rt = runtime_states.get(t["id"]) or {}
        state = "идёт ход" if rt.get("turn") is not None else ("живой" if rt.get("process") is not None else "спит")
        rows.append(f"{t.get('title') or f'{t['chat_id']}:{thread}'} — {t['cwd']} — {state}")
    return "\n".join(rows)
