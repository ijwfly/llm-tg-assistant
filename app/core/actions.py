"""Topic actions shared by slash commands and inline buttons. Each returns a short toast text."""
from __future__ import annotations

import os
import uuid
import zlib
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.methods import CreateForumTopic, DeleteForumTopic, EditForumTopic

import settings
from app.bridge import sessions
from app.bridge.cli import PERMISSION_MODES
from app.bridge.rules import forget_rules as _forget_in_files, local_allow_rules
from app.core import prefs
from app.core.runtime import QueueFull, TurnRequest
from app.render.keyboards import confirm_delete_kb, rewind_confirm_kb, rewind_list_kb, sessions_kb, topic_card_kb
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


async def set_permission_mode(app, topic: dict, mode: str, *, announce: bool = True) -> str:
    if mode not in PERMISSION_MODES or (mode == "bypass" and not settings.ALLOW_BYPASS):
        return texts.PERM_UNKNOWN.format(mode=mode)
    await app.store.topics.update(topic["id"], permission_mode=mode)
    await app.runtimes.get(topic).stop_process()   # the new mode applies on the next spawn, context kept
    if announce:
        await send_to_topic(app, topic, texts.PERM_SET.format(mode=mode))
    return texts.PERM_SET.format(mode=mode)


async def set_model(app, topic: dict, model: str | None, *, announce: bool = True) -> str:
    value = None if not model or model == prefs.DEFAULT else model
    await app.store.topics.update(topic["id"], model=value)
    await app.runtimes.get(topic).stop_process()
    text = texts.MODEL_SET.format(model=prefs.shown(value))
    if announce:
        await send_to_topic(app, topic, text)
    return text


async def set_effort(app, topic: dict, effort: str | None, *, announce: bool = True) -> str:
    value = None if not effort or effort == prefs.DEFAULT else effort
    if value is not None and value not in prefs.EFFORTS:
        text = texts.EFFORT_UNKNOWN.format(effort=effort)
        if announce:
            await send_to_topic(app, topic, text)
        return text
    await app.store.topics.update(topic["id"], effort=value)
    await app.runtimes.get(topic).stop_process()
    text = texts.EFFORT_SET.format(effort=prefs.shown(value))
    if announce:
        await send_to_topic(app, topic, text)
    return text


def _soul_allowed(path: Path) -> bool:
    roots = [Path(settings.WORK_ROOT).resolve(), Path(os.path.expanduser("~/.config")).resolve()]
    return any(path == r or r in path.parents for r in roots)


async def set_soul(app, topic: dict, arg: str) -> str:
    arg = arg.strip()
    if not arg:
        from app.bridge.cli import soul_file
        current = soul_file(topic)
        text = texts.SOUL_INFO.format(path=str(current) if current else ("выключен" if topic.get("soul_path") == "off" else "нет"))
    elif arg == "off":
        await app.store.topics.update(topic["id"], soul_path="off")
        await app.runtimes.get(topic).stop_process()
        text = texts.SOUL_OFF
    elif arg == "default":
        await app.store.topics.update(topic["id"], soul_path=None)
        await app.runtimes.get(topic).stop_process()
        text = texts.SOUL_DEFAULT.format(path=settings.SOUL_PATH or "не задан")
    else:
        path = Path(os.path.expanduser(arg)).resolve()
        if not path.is_file() or not _soul_allowed(path):
            text = texts.SOUL_NO_FILE.format(path=path, root=settings.WORK_ROOT)
        else:
            await app.store.topics.update(topic["id"], soul_path=str(path))
            await app.runtimes.get(topic).stop_process()
            text = texts.SOUL_SET.format(path=path)
    await send_to_topic(app, topic, text)
    return text


async def set_voice(app, topic: dict, arg: str) -> str:
    arg = arg.strip().lower()
    if arg not in ("on", "off"):
        text = texts.VOICE_INFO.format(state="вкл" if prefs.topic_flag(topic, "voice") else "выкл")
    elif arg == "on" and not settings.TTS_CMD:
        text = texts.TTS_NOT_CONFIGURED
    else:
        await app.store.topics.update_settings(topic["id"], voice=(arg == "on"))
        text = texts.VOICE_ON if arg == "on" else texts.VOICE_OFF
    await send_to_topic(app, topic, text)
    return text


async def cycle_setting(app, topic: dict, key: str) -> str:
    """A card switch: next value in the cycle, process restarted, no chat message (the card redraws)."""
    if key == "perm":
        await set_permission_mode(app, topic, prefs.next_in(prefs.perm_cycle(), topic.get("permission_mode")), announce=False)
    elif key == "model":
        await set_model(app, topic, prefs.next_in(prefs.model_cycle(), topic.get("model")), announce=False)
    elif key == "effort":
        await set_effort(app, topic, prefs.next_in(prefs.effort_cycle(), topic.get("effort")), announce=False)
    else:
        return texts.TOAST_STALE
    return texts.TOAST_SWITCHED


async def toggle_flag(app, topic: dict, user_id: int | None, key: str) -> str:
    if key in prefs.TOPIC_FLAGS:
        if key == "voice" and not prefs.topic_flag(topic, key) and not settings.TTS_CMD:
            await send_to_topic(app, topic, texts.TTS_NOT_CONFIGURED)
            return texts.TTS_NOT_CONFIGURED
        await app.store.topics.update_settings(topic["id"], **{key: not prefs.topic_flag(topic, key)})
        return texts.TOAST_SWITCHED
    if key in prefs.USER_FLAGS and user_id:
        current = await app.store.users.settings(user_id)
        await app.store.users.update_settings(user_id, **{key: not prefs.user_flag(current, key)})
        return texts.TOAST_SWITCHED
    return texts.TOAST_STALE


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


async def topic_card(app, topic: dict, *, page: str = "main", user_id: int | None = None) -> tuple[str, object]:
    rt = app.runtimes.peek(topic["id"])
    state = rt.status() if rt else None
    running = bool(state and (state.get("turn") is not None or state.get("queued")))
    staging = await app.store.staging.count(topic["id"])
    title = sessions.session_title(str(topic["session_id"]) if topic["session_id"] else None, topic["cwd"])
    user_settings = await app.store.users.settings(user_id) if user_id else {}
    flags = {k: prefs.topic_flag(topic, k) for k in prefs.TOPIC_FLAGS}
    flags.update({k: prefs.user_flag(user_settings, k) for k in prefs.USER_FLAGS})
    rules = len(await app.store.rules.list(topic["id"])) if page == "more" else 0
    kb = topic_card_kb(topic["id"], running=running, perm=topic.get("permission_mode") or settings.DEFAULT_PERMISSION_MODE,
                       model=prefs.shown(topic.get("model")), effort=prefs.shown(topic.get("effort")),
                       flags=flags, labels=prefs.FLAG_LABELS, page=page, rules=rules, rewind=settings.FILE_CHECKPOINTING)
    return texts.status(topic, state, staging, title, app.runtimes.rate_limit), kb


# ---------------------------------------------------------------- sessions (PROJECT_SPEC 4.2, 4.3.1)

async def _where(app, topic: dict, session_id: str) -> str:
    if str(topic["session_id"]) == session_id:
        return "эта тема"
    if session_id in (topic.get("settings") or {}).get("past_sessions", []):
        return "эта тема, раньше"
    other = await app.store.topics.find_by_session(uuid.UUID(session_id))
    if other:
        return f"тема «{other.get('title') or other['id']}»"
    return ""


def _folder_label(cwd: str | None, root: str) -> str:
    if not cwd:
        return "?"
    try:
        rel = os.path.relpath(Path(cwd).resolve(), Path(root).resolve())
    except ValueError:
        return cwd
    return "." if rel == "." else rel


async def sessions_card(app, topic: dict) -> str:
    """Every session of the machine inside WORK_ROOT (PROJECT_SPEC 4.3.1): the topic's own folder first."""
    root = settings.WORK_ROOT
    found, outside = sessions.machine_sessions(root, first_cwd=topic["cwd"])
    rows, entries = [], []
    topic_dir = Path(topic["cwd"]).resolve()
    for s in found:
        same = Path(s.cwd or "").resolve() == topic_dir
        rows.append((_folder_label(s.cwd, root), s.short, sessions.ago(s.mtime), s.title, await _where(app, topic, s.session_id)))
        entries.append((s.session_id, same))
    text = texts.sessions_card(root, rows, outside)
    kb = sessions_kb(topic["id"], entries) if entries else None
    await send_to_topic(app, topic, text, reply_markup=kb, role="card")
    return text


async def topic_from_session(app, topic: dict, query: str) -> str:
    """`Новая тема <id>` on the sessions card: a topic bound to the session's folder, continuing it."""
    session, error = _lookup(topic, query)
    if error:
        await send_to_topic(app, topic, error)
        return error
    cwd = _usable_cwd(session.cwd)
    if cwd is None:
        text = texts.RESUMED_CWD_KEPT.format(cwd=session.cwd, kept=topic["cwd"])
        await send_to_topic(app, topic, text)
        return text
    name = f"{os.path.basename(cwd)}: {session.title}"[:60]
    new_topic, error = await create_topic(app, topic, name, cwd=cwd, session_id=uuid.UUID(session.session_id),
                                          session_resumable=True)
    if error:
        await send_to_topic(app, topic, error)
        return error
    await send_to_topic(app, topic, texts.PROJECT_OPENED.format(name=name))
    await send_to_topic(app, new_topic, texts.SESSION_TOPIC_HELLO.format(short=session.short, title=session.title[:80], cwd=cwd))
    return texts.PROJECT_OPENED.format(name=name)


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
    if str(topic["session_id"]) != session.session_id:
        await app.store.topics.remember_past_session(topic["id"])
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
    if arg == "new" or arg.startswith("new "):
        return await new_project(app, topic, arg[3:].strip())
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


async def new_project(app, topic: dict, name: str) -> str:
    """`/project new <имя>`: folder under NEW_PROJECTS_DIR (or WORK_ROOT) + fresh session + topic."""
    base = Path(settings.NEW_PROJECTS_DIR or settings.WORK_ROOT).resolve()
    if not name:
        text = texts.PROJECT_NEW_USAGE.format(dir=base)
        await send_to_topic(app, topic, text)
        return text
    if "/" in name or name in (".", "..") or name.startswith(".") or len(name) > 80:
        await send_to_topic(app, topic, texts.PROJECT_NEW_BAD_NAME)
        return texts.PROJECT_NEW_BAD_NAME
    path = base / name
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    new_topic, error = await create_topic(app, topic, name, cwd=str(path), session_id=uuid.uuid4())
    if error:
        await send_to_topic(app, topic, error)
        return error
    if created:
        await send_to_topic(app, topic, texts.PROJECT_NEW_CREATED.format(path=path))
    await send_to_topic(app, topic, texts.PROJECT_OPENED.format(name=name))
    await send_to_topic(app, new_topic, texts.PROJECT_HELLO.format(path=path))
    return texts.PROJECT_OPENED.format(name=name)


async def ask_delete_topic(app, topic: dict, message_id: int | None = None) -> str:
    """Confirmation step: redraw the card (or send one) with «Да, удалить тему» / «Отмена»."""
    if not topic["thread_id"]:
        await send_to_topic(app, topic, texts.DELETE_NOT_A_TOPIC)
        return texts.DELETE_NOT_A_TOPIC
    text = texts.DELETE_CONFIRM.format(name=topic.get("title") or topic["thread_id"])
    if message_id:
        await app.sender.edit_text(topic["chat_id"], topic["thread_id"], message_id, text,
                                   reply_markup=confirm_delete_kb(topic["id"]), topic_id=topic["id"])
    else:
        await send_to_topic(app, topic, text, reply_markup=confirm_delete_kb(topic["id"]), role="card")
    return ""


async def delete_topic(app, topic: dict) -> str:
    """Delete the Telegram topic (only the bot can delete topics it created in private chats) and forget it.
    Direct Bot API call: the outcome decides whether the DB row goes."""
    if not topic["thread_id"]:
        return texts.DELETE_NOT_A_TOPIC
    try:
        await app.bot(DeleteForumTopic(chat_id=topic["chat_id"], message_thread_id=topic["thread_id"]))
    except TelegramAPIError as e:
        reason = getattr(e, "message", None) or str(e)
        await send_to_topic(app, topic, texts.DELETE_FAILED.format(reason=reason))
        return texts.DELETE_FAILED.format(reason=reason)
    await app.runtimes.drop(topic["id"])
    await app.store.topics.delete(topic["id"])
    return texts.TOAST_DELETED


async def usage_card(app, topic: dict) -> str:
    from datetime import date
    from app.render.keyboards import hide_kb
    rows = await app.store.turns.month_usage()
    text = texts.usage_card(rows, date.today().strftime("%Y-%m"))
    await send_to_topic(app, topic, text, reply_markup=hide_kb(topic["id"]), role="card")
    return text


# ---------------------------------------------------------------- rewind (PROJECT_SPEC 4.3, FILE_CHECKPOINTING)

def _prompt_label(turn: dict, limit: int = 40) -> str:
    text = " ".join(b.get("text", "") for b in (turn.get("prompt") or []) if b.get("type") == "text")
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


async def rewind_list(app, topic: dict) -> str:
    turns = await app.store.turns.with_checkpoints(topic["id"])
    if not turns:
        await send_to_topic(app, topic, texts.REWIND_EMPTY)
        return texts.REWIND_EMPTY
    await send_to_topic(app, topic, texts.REWIND_LIST,
                        reply_markup=rewind_list_kb(topic["id"], [(t["id"], _prompt_label(t)) for t in turns]), role="card")
    return ""


async def rewind_ask(app, topic: dict, turn_id: int, message_id: int | None) -> str:
    turn = await app.store.turns.get(turn_id)
    if not turn or turn["topic_id"] != topic["id"] or not turn.get("checkpoint_uuid"):
        return texts.TOAST_STALE
    text = texts.REWIND_CONFIRM.format(prompt=_prompt_label(turn))
    if message_id:
        await app.sender.edit_text(topic["chat_id"], topic["thread_id"], message_id, text,
                                   reply_markup=rewind_confirm_kb(topic["id"], turn_id), topic_id=topic["id"])
    else:
        await send_to_topic(app, topic, text, reply_markup=rewind_confirm_kb(topic["id"], turn_id), role="card")
    return ""


async def rewind(app, topic: dict, turn_id: int, message_id: int | None) -> str:
    """`claude -p --resume <id> --rewind-files <uuid>` is a standalone operation: stop the topic's process,
    run it once, report its one-line result."""
    import asyncio
    from app.bridge.cli import child_env
    turn = await app.store.turns.get(turn_id)
    if not turn or turn["topic_id"] != topic["id"] or not turn.get("checkpoint_uuid") or not topic["session_id"]:
        return texts.TOAST_STALE
    await app.runtimes.get(topic).stop_process()
    argv = [settings.CLAUDE_BIN, "-p", "--resume", str(topic["session_id"]), "--rewind-files", turn["checkpoint_uuid"]]
    try:
        proc = await asyncio.create_subprocess_exec(*argv, cwd=topic["cwd"], env=child_env(), stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    except (OSError, asyncio.TimeoutError) as e:
        text = texts.REWIND_FAILED.format(reason=repr(e))
    else:
        if proc.returncode == 0:
            text = texts.REWIND_DONE.format(text=(out.decode(errors="replace").strip() or "files rewound")[:300])
        else:
            text = texts.REWIND_FAILED.format(reason=(err.decode(errors="replace").strip() or f"code {proc.returncode}")[-300:])
    if message_id:
        await app.sender.edit_text(topic["chat_id"], topic["thread_id"], message_id, text, topic_id=topic["id"])
    else:
        await send_to_topic(app, topic, text)
    return texts.TOAST_REWOUND if text.startswith("⏪") else texts.TOAST_FAILED


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


async def show_card(app, topic: dict, user_id: int | None = None) -> None:
    text, kb = await topic_card(app, topic, user_id=user_id)
    await send_to_topic(app, topic, text, reply_markup=kb, role="card")


async def refresh_card(app, topic: dict, message_id: int, *, page: str = "main", user_id: int | None = None) -> str:
    text, kb = await topic_card(app, topic, page=page, user_id=user_id)
    await app.sender.edit_text(topic["chat_id"], topic["thread_id"], message_id, text, reply_markup=kb,
                               topic_id=topic["id"])
    return texts.TOAST_REFRESHED


async def hide_card(app, topic: dict, message_id: int) -> str:
    await app.sender.delete(topic["chat_id"], topic["thread_id"], message_id, topic_id=topic["id"])
    return ""
