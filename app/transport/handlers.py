"""Command and message handlers. `app` is injected from dispatcher workflow data."""
from __future__ import annotations

import os
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, MessageGenerationStopped

import settings
from app.core import actions
from app.core.topics import TopicRef
from app.transport import texts
from app.transport.callbacks import on_callback

CONTENT_FILTER = F.text | F.caption | F.photo | F.document | F.voice | F.audio | F.video_note | F.video


def topic_ref(message: Message) -> TopicRef:
    thread = message.message_thread_id if message.is_topic_message else None
    return TopicRef(message.chat.id, thread)


def topic_title(message: Message) -> str | None:
    if message.chat.type == "private" and not message.is_topic_message:
        return None
    if message.is_topic_message and message.reply_to_message and message.reply_to_message.forum_topic_created:
        return message.reply_to_message.forum_topic_created.name
    return message.chat.title


async def _remember_user(app, message: Message) -> None:
    u = message.from_user
    if u is not None:
        await app.store.users.upsert(u.id, u.full_name, u.username)


def _implicit_title(message: Message) -> bool:
    created = message.reply_to_message.forum_topic_created if message.is_topic_message and message.reply_to_message else None
    return bool(created and created.is_name_implicit)


async def _topic(app, message: Message) -> dict:
    await _remember_user(app, message)
    topic = await app.topics.get_or_create(topic_ref(message), topic_title(message))
    if _implicit_title(message) and "title_implicit" not in (topic.get("settings") or {}):
        topic = await app.store.topics.update_settings(topic["id"], title_implicit=True)   # False after a rename
    return topic


# ------------------------------------------------------------------ commands

async def cmd_help(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.HELP)


async def cmd_whoami(message: Message, app) -> None:
    ref = topic_ref(message)
    await app.sender.send_text(ref.chat_id, ref.thread_id,
                               texts.whoami(message.from_user.id, ref.chat_id, ref.thread_id))


async def cmd_topics(message: Message, app) -> None:
    ref = topic_ref(message)
    topics = await app.topics.list_all()
    states = {t["id"]: rt.status() for t in topics if (rt := app.runtimes.peek(t["id"]))}
    await app.sender.send_text(ref.chat_id, ref.thread_id, texts.topics_list(topics, states))


async def cmd_status(message: Message, app) -> None:
    await actions.show_card(app, await _topic(app, message), user_id=message.from_user.id if message.from_user else None)


async def cmd_model(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    arg = (command.args or "").strip()
    if not arg:
        from app.core import prefs
        await actions.send_to_topic(app, topic, texts.MODEL_INFO.format(
            model=prefs.shown(topic.get("model")), choices=", ".join(settings.MODEL_CHOICES)))
        return
    await actions.set_model(app, topic, arg)


async def cmd_effort(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    arg = (command.args or "").strip()
    if not arg:
        from app.core import prefs
        await actions.send_to_topic(app, topic, texts.EFFORT_INFO.format(effort=prefs.shown(topic.get("effort"))))
        return
    await actions.set_effort(app, topic, arg)


async def cmd_soul(message: Message, command: CommandObject, app) -> None:
    await actions.set_soul(app, await _topic(app, message), command.args or "")


async def cmd_usage(message: Message, app) -> None:
    await actions.usage_card(app, await _topic(app, message))


async def cmd_voice(message: Message, command: CommandObject, app) -> None:
    await actions.set_voice(app, await _topic(app, message), command.args or "")


async def cmd_new(message: Message, app) -> None:
    await actions.new_context(app, await _topic(app, message))


async def cmd_stop(message: Message, app) -> None:
    await actions.stop_process(app, await _topic(app, message))


async def cmd_cancel(message: Message, app) -> None:
    ref = topic_ref(message)
    topic = await app.topics.get(ref)
    if topic is None:
        await app.sender.send_text(ref.chat_id, ref.thread_id, texts.NOTHING_TO_CANCEL)
        return
    await actions.cancel_turn(app, topic)


async def cmd_retry(message: Message, app) -> None:
    await actions.retry_last(app, await _topic(app, message))


async def cmd_files(message: Message, app) -> None:
    topic = await _topic(app, message)
    await actions.send_to_topic(app, topic, texts.files_list(await app.inbox.list_recent(topic["id"])))


def resolve_cwd(raw: str) -> tuple[str | None, str | None]:
    """(path, error_text). The path must exist and live inside WORK_ROOT."""
    path = Path(os.path.expanduser(raw.strip())).resolve()
    root = Path(settings.WORK_ROOT).resolve()
    if not path.is_dir():
        return None, texts.CD_NO_DIR.format(path=path)
    if path != root and root not in path.parents:
        return None, texts.CD_OUTSIDE.format(path=path, root=root)
    return str(path), None


async def _change_dir(app, topic: dict, raw: str) -> None:
    path, error = resolve_cwd(raw)
    if error:
        await actions.send_to_topic(app, topic, error)
        return
    await app.runtimes.get(topic).restart_context(cwd=path)
    await actions.send_to_topic(app, topic, texts.CD_OK.format(path=path))


async def cmd_cd(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    if not command.args:
        await actions.send_to_topic(app, topic, texts.CD_USAGE)
        return
    await _change_dir(app, topic, command.args)


async def cmd_go(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    alias = (command.args or "").strip()
    if not alias:
        await actions.send_to_topic(app, topic, texts.go_list(settings.PROJECTS) if settings.PROJECTS else texts.GO_EMPTY)
        return
    if alias not in settings.PROJECTS:
        await actions.send_to_topic(app, topic, texts.GO_UNKNOWN.format(alias=alias))
        return
    await _change_dir(app, topic, settings.PROJECTS[alias])


async def cmd_sessions(message: Message, app) -> None:
    await actions.sessions_card(app, await _topic(app, message))


async def cmd_resume(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    if not (command.args or "").strip():
        await actions.send_to_topic(app, topic, texts.RESUME_USAGE)
        return
    await actions.resume_session(app, topic, command.args.strip())


async def cmd_branch(message: Message, command: CommandObject, app) -> None:
    await actions.branch(app, await _topic(app, message), (command.args or "").strip() or None)


async def cmd_project(message: Message, command: CommandObject, app) -> None:
    await actions.project_topic(app, await _topic(app, message), command.args or "")


async def cmd_rename(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    if not (command.args or "").strip():
        await actions.send_to_topic(app, topic, texts.RENAME_USAGE)
        return
    await actions.rename_topic(app, topic, command.args.strip())


async def cmd_delete(message: Message, app) -> None:
    await actions.ask_delete_topic(app, await _topic(app, message))


async def cmd_perm(message: Message, command: CommandObject, app) -> None:
    topic = await _topic(app, message)
    mode = (command.args or "").strip()
    if not mode:
        await actions.send_to_topic(app, topic, await actions.perm_info(app, topic))
        return
    if mode == "forget":
        await actions.forget_rules(app, topic)
        return
    if mode == "default":
        mode = settings.DEFAULT_PERMISSION_MODE
    toast = await actions.set_permission_mode(app, topic, mode)
    if toast.startswith("Не знаю"):
        await actions.send_to_topic(app, topic, toast)


# ------------------------------------------------------------------ turns

async def any_message(message: Message, app) -> None:
    """Everything that is not a bridge command goes through the batcher (PROJECT_SPEC 4.4)."""
    topic = await _topic(app, message)
    if message.text and await app.prompts.consume_text(topic, message.text):
        return   # the text answered a card that asked for it (deny comment, custom answer, plan rework)
    app.batcher.add(topic, message)


async def edited_message(message: Message, app) -> None:
    if not (message.text or message.caption):
        return
    topic = await _topic(app, message)
    app.batcher.add(topic, message, flag="edited")


async def on_generation_stopped(event: MessageGenerationStopped, app) -> None:
    topic = await app.topics.get(TopicRef(event.chat.id, event.message_thread_id))
    rt = app.runtimes.peek(topic["id"]) if topic else None
    if rt is not None:
        await rt.cancel()


async def on_callback_query(cq: CallbackQuery, app) -> None:
    await on_callback(cq, app)


def build_router() -> Router:
    """A fresh Router per Dispatcher: aiogram routers cannot be attached twice."""
    router = Router(name="bridge")
    router.message.register(cmd_help, Command("help", "start"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(cmd_topics, Command("topics"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_new, Command("new", "clear"))
    router.message.register(cmd_stop, Command("stop"))
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(cmd_retry, Command("retry"))
    router.message.register(cmd_cd, Command("cd"))
    router.message.register(cmd_go, Command("go"))
    router.message.register(cmd_perm, Command("perm"))
    router.message.register(cmd_files, Command("files"))
    router.message.register(cmd_sessions, Command("sessions"))
    router.message.register(cmd_resume, Command("resume"))
    router.message.register(cmd_branch, Command("branch"))
    router.message.register(cmd_project, Command("project"))
    router.message.register(cmd_rename, Command("rename"))
    router.message.register(cmd_delete, Command("delete"))
    router.message.register(cmd_model, Command("model"))
    router.message.register(cmd_effort, Command("effort"))
    router.message.register(cmd_soul, Command("soul"))
    router.message.register(cmd_voice, Command("voice"))
    router.message.register(cmd_usage, Command("usage"))
    router.message.register(any_message, CONTENT_FILTER)
    router.edited_message.register(edited_message, CONTENT_FILTER)
    router.stopped_message_generation.register(on_generation_stopped)
    router.callback_query.register(on_callback_query)
    return router
