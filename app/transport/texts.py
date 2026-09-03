"""All user-facing strings of the bot live here (Russian)."""
from app.render.markdown import format_duration

HELP = (
    "Я управляю сессиями Claude Code на сервере. Каждая тема — своя сессия.\n\n"
    "Просто пиши — это ход Claude Code. Reply на сообщение цитирует его.\n\n"
    "/new — новый контекст (старая сессия остаётся на диске)\n"
    "/cancel — прервать текущий ход\n"
    "/retry — повторить последний ход\n"
    "/stop — погасить процесс, контекст сохранить\n"
    "/cd <путь>, /go [алиас] — сменить директорию (контекст заново)\n"
    "/status — состояние темы\n"
    "/topics — список тем\n"
    "/whoami — твой id, чат и тема\n"
    "/help — эта справка\n\n"
    "Остальные /команды (/compact, /cost, /context…) уходят в Claude Code как есть."
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
DENIED = "🔒 Отклонено без спроса: {tools}\nКнопки разрешений появятся позже; пока помогает /perm acceptEdits или правила ALLOWED_TOOLS."
TURN_TIMEOUT = "⏱ Ход шёл дольше лимита и был прерван. Контекст сохранён."
DAEMON_STOPPED = "⏹ Демон остановлен посреди хода. Контекст цел — /retry повторит."
COMPACTED = "🧹 Контекст сжат: было {pre_tokens} токенов."
TURN_INTERNAL_ERROR = "💥 Внутренняя ошибка моста при обработке хода. Подробности в логе; /retry повторит."


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


def status(topic: dict, rt: dict | None) -> str:
    thread = topic["thread_id"] if topic["thread_id"] is not None else "—"
    rt = rt or {}
    proc = rt.get("process")
    turn = rt.get("turn")
    lines = [
        f"Тема         {topic.get('title') or '—'} ({topic['chat_id']}:{thread})",
        f"Сессия       {topic['session_id'] or 'ещё нет'}",
        f"Директория   {topic['cwd']}",
        f"Модель       {topic['model'] or 'по умолчанию'}   Усилие  {topic['effort'] or 'по умолчанию'}",
        f"Права        {topic['permission_mode'] or 'по умолчанию'}",
        f"Процесс      {'живой, ' + format_duration(int(proc * 1000)) if proc is not None else 'спит'}",
        f"Ход          {'идёт ' + format_duration(int(turn * 1000)) if turn is not None else 'нет'}"
        + (f" · в очереди {rt['queued']}" if rt.get("queued") else ""),
    ]
    last = rt.get("last")
    if last:
        lines.append("Последний    " + turn_stats(last.get("duration_ms"), last.get("cost_usd"), last.get("num_turns")).strip("_"))
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
