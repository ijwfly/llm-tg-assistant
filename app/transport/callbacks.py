"""Inline-button callbacks. Buttons and commands share the functions in app/core/actions.py."""
from __future__ import annotations

import logging

from aiogram.types import CallbackQuery

from app.core import actions
from app.render.keyboards import parse_cb
from app.transport import texts

log = logging.getLogger(__name__)


async def _refresh_after(app, topic: dict, cq: CallbackQuery, page: str = "main") -> None:
    """A card button changed the topic: redraw the card it lives on."""
    if cq.message is not None:
        topic = await app.store.topics.get_by_id(topic["id"]) or topic
        await actions.refresh_card(app, topic, cq.message.message_id, page=page, user_id=cq.from_user.id)


PROMPT_ACTIONS = {"pa", "pd", "pw", "pc", "qo", "qd", "qc", "pl"}


async def _prompt_action(app, action: str, arg: str, message_id: int | None) -> str:
    """arg = "<prompt_id>[:<extra>]"."""
    pid, _, extra = arg.partition(":")
    if not pid.isdigit():
        return texts.TOAST_PROMPT_STALE
    prompt_id = int(pid)
    prompts = app.prompts
    if action == "pa":
        return await prompts.permission(prompt_id, "allow", message_id)
    if action == "pd":
        return await prompts.permission(prompt_id, "deny", message_id)
    if action == "pw":
        return await prompts.permission(prompt_id, "always", message_id)
    if action == "pc":
        return await prompts.permission(prompt_id, "comment", message_id)
    if action == "qo":
        return await prompts.question_option(prompt_id, int(extra) if extra.isdigit() else -1, message_id)
    if action == "qd":
        return await prompts.question_done(prompt_id, message_id)
    if action == "qc":
        return await prompts.question_custom(prompt_id, message_id)
    if action == "pl":
        return await prompts.plan(prompt_id, extra, message_id)
    return texts.TOAST_PROMPT_STALE


async def _full_session_id(topic: dict, prefix: str) -> str | None:
    from app.bridge.sessions import find_sessions
    matches = find_sessions(prefix, topic["cwd"])
    return matches[0].session_id if len(matches) == 1 else None


async def on_callback(cq: CallbackQuery, app) -> None:
    parsed = parse_cb(cq.data or "")
    if parsed is None:
        await cq.answer(texts.TOAST_STALE)
        return
    action, topic_id, arg = parsed
    topic = await app.store.topics.get_by_id(topic_id)
    if topic is None:
        await cq.answer(texts.TOAST_STALE)
        return
    try:
        if action == "cancel":
            toast = await actions.cancel_turn(app, topic)
        elif action == "retry":
            toast = await actions.retry_last(app, topic)
        elif action == "continue":
            toast = await actions.continue_turn(app, topic)
        elif action == "new":
            toast = await actions.new_context(app, topic)
            await _refresh_after(app, topic, cq)
        elif action == "stop":
            toast = await actions.stop_process(app, topic)
            await _refresh_after(app, topic, cq)
        elif action == "perm":
            toast = await actions.set_permission_mode(app, topic, arg or "")
        elif action == "refresh":
            toast = await actions.refresh_card(app, topic, cq.message.message_id, user_id=cq.from_user.id) if cq.message else texts.TOAST_STALE
        elif action == "page":
            toast = await actions.refresh_card(app, topic, cq.message.message_id, page=arg or "main", user_id=cq.from_user.id) if cq.message else texts.TOAST_STALE
        elif action == "cyc":
            toast = await actions.cycle_setting(app, topic, arg or "")
            await _refresh_after(app, topic, cq)
        elif action == "forget":
            toast = await actions.forget_rules(app, topic)
            await _refresh_after(app, topic, cq, page="more")
        elif action == "tgl":
            toast = await actions.toggle_flag(app, topic, cq.from_user.id, arg or "")
            await _refresh_after(app, topic, cq, page="more")
        elif action == "hide":
            toast = await actions.hide_card(app, topic, cq.message.message_id) if cq.message else texts.TOAST_STALE
        elif action == "del":
            toast = await actions.ask_delete_topic(app, topic, cq.message.message_id if cq.message else None)
        elif action == "delc":
            toast = await actions.delete_topic(app, topic)
        elif action == "sessions":
            toast = await actions.sessions_card(app, topic) and ""
        elif action == "branch":
            toast = await actions.branch(app, topic)
        elif action == "rs":
            toast = await actions.resume_session(app, topic, arg or "")
        elif action == "ns":
            toast = await actions.topic_from_session(app, topic, arg or "")
        elif action == "br":
            toast = await actions.branch(app, topic, from_session=(await _full_session_id(topic, arg or "")))
        elif action in PROMPT_ACTIONS:
            toast = await _prompt_action(app, action, arg or "", cq.message.message_id if cq.message else None)
        else:
            toast = texts.TOAST_STALE
    except Exception:
        log.exception("callback %s failed", cq.data)
        toast = texts.TOAST_FAILED
    await cq.answer(toast or None)
