"""All user-facing strings of the bot live here (Russian)."""

HELP = (
    "Я управляю сессиями Claude Code на сервере. Каждая тема — своя сессия.\n\n"
    "/status — состояние темы\n"
    "/topics — список тем\n"
    "/whoami — твой id, чат и тема\n"
    "/help — эта справка\n\n"
    "Остальные /команды уходят в Claude Code как есть."
)

NOT_AUTHORIZED = "Not authorized"
TOPICS_EMPTY = "Пока пусто."
TURNS_NOT_YET = "🚧 Ходы появятся в фазе 2. Тема создана: {cwd}"

STARTUP = "🌅 Я на месте. Бот @{username}, режим {mode}, тем: {topics}, версия {version}"
SHUTDOWN = "⏹ Останавливаюсь."


def whoami(user_id: int, chat_id: int, thread_id: int | None) -> str:
    return f"Твой id: {user_id}\nЧат: {chat_id}\nТема: {thread_id if thread_id is not None else '—'}"


def status(topic: dict) -> str:
    thread = topic["thread_id"] if topic["thread_id"] is not None else "—"
    lines = [
        f"Тема         {topic.get('title') or '—'} ({topic['chat_id']}:{thread})",
        f"Сессия       {topic['session_id'] or 'ещё нет'}",
        f"Директория   {topic['cwd']}",
        f"Модель       {topic['model'] or 'по умолчанию'}   Усилие  {topic['effort'] or 'по умолчанию'}",
        f"Права        {topic['permission_mode'] or 'по умолчанию'}",
        "Процесс      спит",
        "Ход          нет",
    ]
    return "\n".join(lines)


def topics_list(topics: list[dict]) -> str:
    if not topics:
        return TOPICS_EMPTY
    rows = []
    for t in topics:
        thread = t["thread_id"] if t["thread_id"] is not None else "—"
        rows.append(f"{t.get('title') or f'{t['chat_id']}:{thread}'} — {t['cwd']} — спит")
    return "\n".join(rows)
