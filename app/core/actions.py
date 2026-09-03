"""Topic actions shared by slash commands and inline buttons. Each returns a short toast text."""
from __future__ import annotations

import os
import uuid
import zlib
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.methods import CreateForumTopic, EditForumTopic

import settings
from app.bridge import sessions
from app.bridge.cli import PERMISSION_MODES
from app.bridge.rules import forget_rules as _forget_in_files, local_allow_rules
from app.core.runtime import QueueFull, TurnRequest
from app.render.keyboards import sessions_kb, topic_card_kb
from app.transport import texts

ICON_COLORS = [0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F]   # the six Telegram allows


async def send_to_topic(app, topic: dict, text: str, *, reply_markup=None, turn_id: int | None = None,
                        role: str = "bot") -> int:
    return await app.sender.send_text(topic["chat_id"], topic["thread_id"], text, reply_markup=reply_markup,
                                      topic_id=topic["id"], turn_id=turn_id, role=role)


async def new_context(app, topic: dict) -> str:
    await app.runtimes.get(topic).restart_context()
    await app.store.staging.clear(topic["id"])
    await send_to_topic(app, topic, texts.NEW_CONTEXT)
    return texts.TOAST_NEW


async def stop_process(app, topic: dict) -> str:
    await app.runtimes.get(topic).stop_process()
    await send_to_topic(app, topic, texts.PROCESS_STOPPED)
    return texts.TOAST_STOPPED


async def cancel_turn(app, topic: dict) -> str:
    rt = app.runtimes.peek(topic["id"])
    if rt is None or not await rt.cancel():
        await send_to_topic(app, topic, texts.NOTHING_TO_CANCEL)
        return texts.NOTHING_TO_CANCEL
    return texts.TOAST_CANCELLING


async def submit_turn(app, topic: dict, request: TurnRequest) -> str:
    rt = app.runtimes.get(topic)
    try:
        busy = await rt.submit(request)
    except QueueFull:
        await send_to_topic(app, topic, texts.QUEUE_FULL)
        return texts.QUEUE_FULL
    if busy and rt.current is not None and not rt.current.hint_sent:
        rt.current.hint_sent = True
        from app.render.keyboards import cancel_kb
        await send_to_topic(app, topic, texts.QUEUE_HINT, reply_markup=cancel_kb(topic["id"], "🛑 Прервать текущий"))
    return texts.TOAST_QUEUED if busy else texts.TOAST_SENT


async def retry_last(app, topic: dict) -> str:
    last = await app.store.turns.last_for_topic(topic["id"])
    if last is None:
        await send_to_topic(app, topic, texts.NOTHING_TO_RETRY)
        return texts.NOTHING_TO_RETRY
    return await submit_turn(app, topic, TurnRequest(content=last["prompt"]))


async def continue_turn(app, topic: dict) -> str:
    return await submit_turn(app, topic, TurnRequest(content=[{"type": "text", "text": "продолжай"}]))


async def set_permission_mode(app, topic: dict, mode: str) -> str:
    if mode not in PERMISSION_MODES or (mode == "bypass" and not settings.ALLOW_BYPASS):
        return texts.PERM_UNKNOWN.format(mode=mode)
    await app.store.topics.update(topic["id"], permission_mode=mode)
    await app.runtimes.get(topic).stop_process()   # the new mode applies on the next spawn, context kept
    await send_to_topic(app, topic, texts.PERM_SET.format(mode=mode))
    return texts.PERM_SET.format(mode=mode)


async def perm_info(app, topic: dict) -> str:
    topic_rules = await app.store.rules.list(topic["id"])
    return texts.perm_info(topic["permission_mode"], topic_rules, local_allow_rules(topic["cwd"], settings.WORK_ROOT))


async def forget_rules(app, topic: dict) -> str:
    rules = await app.store.rules.list(topic["id"])
    if not rules:
        await send_to_topic(app, topic, texts.PERM_NOTHING_TO_FORGET)
        return texts.PERM_NOTHING_TO_FORGET
    _forget_in_files(topic["cwd"], settings.WORK_ROOT, rules)
    await app.store.rules.clear(topic["id"])
    text = texts.PERM_FORGOT.format(n=len(rules))
    await send_to_topic(app, topic, text)
    return text


async def topic_card(app, topic: dict) -> tuple[str, object]:
    rt = app.runtimes.peek(topic["id"])
    state = rt.status() if rt else None
    running = bool(state and (state.get("turn") is not None or state.get("queued")))
    staging = await app.store.staging.count(topic["id"])
    title = sessions.session_title(str(topic["session_id"]) if topic["session_id"] else None, topic["cwd"])
    return texts.status(topic, state, staging, title), topic_card_kb(topic["id"], running=running)


# ---------------------------------------------------------------- sessions (PROJECT_SPEC 4.2, 4.3.1)

async def _where(app, topic: dict, session_id: str) -> str:
    if str(topic["session_id"]) == session_id:
        return "эта тема"
    other = await app.store.topics.find_by_session(uuid.UUID(session_id))
    if other:
        return f"тема «{other.get('title') or other['id']}»"
    return "терминал"


async def sessions_card(app, topic: dict) -> str:
    found = sessions.list_sessions(topic["cwd"])
    rows = [(s.short, sessions.ago(s.mtime), s.title, await _where(app, topic, s.session_id)) for s in found]
    text = texts.sessions_card(topic["cwd"], rows)
    kb = sessions_kb(topic["id"], [s.session_id for s in found]) if found else None
    await send_to_topic(app, topic, text, reply_markup=kb, role="card")
    return text


def _lookup(topic: dict, query: str) -> tuple[sessions.SessionInfo | None, str | None]:
    """(session, error_text)."""
    matches = sessions.find_sessions(query, topic["cwd"])
    if not matches:
        return None, texts.SESSION_NOT_FOUND.format(query=query)
    if len(matches) > 1:
        rows = "\n".join(f"▸ {m.short} · «{m.title[:60]}»" for m in matches[:8])
        return None, texts.SESSION_AMBIGUOUS.format(query=query, rows=rows)
    return matches[0], None


def _usable_cwd(session_cwd: str | None) -> str | None:
    if not session_cwd:
        return None
    path = Path(session_cwd)
    root = Path(settings.WORK_ROOT).resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if resolved.is_dir() and (resolved == root or root in resolved.parents):
        return str(resolved)
    return None


async def resume_session(app, topic: dict, query: str) -> str:
    session, error = _lookup(topic, query)
    if error:
        await send_to_topic(app, topic, error)
        return error
    await app.runtimes.get(topic).stop_process()
    fields = {"session_id": uuid.UUID(session.session_id), "session_resumable": True}
    cwd = _usable_cwd(session.cwd)
    if cwd:
        fields["cwd"] = cwd
    await app.store.topics.update_settings(topic["id"], fork=None)
    updated = await app.store.topics.update(topic["id"], **fields)
    await send_to_topic(app, topic, texts.RESUMED.format(short=session.short, title=session.title[:80], cwd=updated["cwd"]))
    if session.cwd and not cwd:
        await send_to_topic(app, topic, texts.RESUMED_CWD_KEPT.format(cwd=session.cwd, kept=updated["cwd"]))
    return texts.TOAST_RESUMED


# ---------------------------------------------------------------- creating topics

def icon_color(name: str) -> int:
    return ICON_COLORS[zlib.crc32(name.encode()) % len(ICON_COLORS)]


async def create_topic(app, source: dict, name: str, *, cwd: str, session_id, session_resumable: bool = False,
                       topic_settings: dict | None = None) -> tuple[dict | None, str | None]:
    """A new forum topic in the source topic's chat plus its DB row. This is the one place that calls the
    Bot API directly: the thread id is needed before anything else can be sent."""
    try:
        forum = await app.bot(CreateForumTopic(chat_id=source["chat_id"], name=name[:128], icon_color=icon_color(name)))
    except TelegramAPIError as e:
        reason = getattr(e, "message", None) or str(e)
        return None, texts.TOPIC_CREATE_FAILED.format(reason=reason)
    topic = await app.store.topics.create(
        source["chat_id"], forum.message_thread_id, cwd=cwd, title=name[:128],
        permission_mode=source.get("permission_mode") or settings.DEFAULT_PERMISSION_MODE,
        model=source.get("model"), effort=source.get("effort"), session_id=session_id,
        session_resumable=session_resumable, settings=topic_settings)
    return topic, None


async def branch(app, topic: dict, name: str | None = None, from_session: str | None = None) -> str:
    source_id = from_session or (str(topic["session_id"]) if topic["session_id"] else None)
    if not source_id:
        await send_to_topic(app, topic, texts.NOTHING_TO_RETRY)
        return texts.NOTHING_TO_RETRY
    if from_session is None or str(topic["session_id"]) == from_session:
        await app.runtimes.get(topic).stop_process()   # flush the transcript so the fork sees everything
    title = name or f"{topic.get('title') or source_id[:8]} · ветка"
    fork = {"from": source_id}
    if name:
        fork["name"] = name
    new_topic, error = await create_topic(app, topic, title, cwd=topic["cwd"], session_id=uuid.UUID(source_id),
                                          session_resumable=True, topic_settings={"fork": fork})
    if error:
        await send_to_topic(app, topic, error)
        return error
    await send_to_topic(app, topic, texts.BRANCH_OPENED.format(name=title))
    await send_to_topic(app, new_topic, texts.BRANCH_HELLO.format(short=source_id[:8]))
    return texts.TOAST_BRANCHED


async def project_topic(app, topic: dict, arg: str) -> str:
    from app.transport.handlers import resolve_cwd
    arg = arg.strip()
    if not arg:
        text = texts.PROJECT_USAGE + ("\n" + texts.go_list(settings.PROJECTS) if settings.PROJECTS else "")
        await send_to_topic(app, topic, text)
        return text
    raw = settings.PROJECTS.get(arg, arg)
    name = arg if arg in settings.PROJECTS else os.path.basename(os.path.normpath(os.path.expanduser(raw))) or raw
    path, error = resolve_cwd(raw)
    if error:
        await send_to_topic(app, topic, error)
        return error
    new_topic, error = await create_topic(app, topic, name, cwd=path, session_id=uuid.uuid4())
    if error:
        await send_to_topic(app, topic, error)
        return error
    await send_to_topic(app, topic, texts.PROJECT_OPENED.format(name=name))
    await send_to_topic(app, new_topic, texts.PROJECT_HELLO.format(path=path))
    return texts.PROJECT_OPENED.format(name=name)


async def rename_topic(app, topic: dict, name: str, *, tell_claude: bool = True) -> str:
    name = " ".join(name.split())[:128]
    await app.store.topics.update(topic["id"], title=name)
    await app.store.topics.update_settings(topic["id"], title_implicit=False)
    if topic["thread_id"]:
        await app.sender.enqueue(f"{topic['chat_id']}:{topic['thread_id']}",
                                 EditForumTopic(chat_id=topic["chat_id"], message_thread_id=topic["thread_id"], name=name),
                                 topic_id=topic["id"], role="edit")
    await send_to_topic(app, topic, texts.RENAMED.format(name=name))
    if tell_claude and topic["session_id"]:
        await submit_turn(app, topic, TurnRequest(content=[{"type": "text", "text": f"/rename {name}"}], quiet=True))
    return texts.RENAMED.format(name=name)


async def show_card(app, topic: dict) -> None:
    text, kb = await topic_card(app, topic)
    await send_to_topic(app, topic, text, reply_markup=kb, role="card")


async def refresh_card(app, topic: dict, message_id: int) -> str:
    text, kb = await topic_card(app, topic)
    await app.sender.edit_text(topic["chat_id"], topic["thread_id"], message_id, text, reply_markup=kb,
                               topic_id=topic["id"])
    return texts.TOAST_REFRESHED


async def hide_card(app, topic: dict, message_id: int) -> str:
    await app.sender.delete(topic["chat_id"], topic["thread_id"], message_id, topic_id=topic["id"])
    return ""
