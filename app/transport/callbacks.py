"""Inline-button callbacks. Buttons and commands share the functions in app/core/actions.py."""
from __future__ import annotations

import logging

from aiogram.types import CallbackQuery

from app.core import actions
from app.render.keyboards import parse_cb
from app.transport import texts

log = logging.getLogger(__name__)


async def _refresh_after(app, topic: dict, cq: CallbackQuery) -> None:
    """A card button changed the topic: redraw the card it lives on."""
    if cq.message is not None:
        topic = await app.store.topics.get_by_id(topic["id"]) or topic
        await actions.refresh_card(app, topic, cq.message.message_id)


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
            toast = await actions.refresh_card(app, topic, cq.message.message_id) if cq.message else texts.TOAST_STALE
        elif action == "hide":
            toast = await actions.hide_card(app, topic, cq.message.message_id) if cq.message else texts.TOAST_STALE
        else:
            toast = texts.TOAST_STALE
    except Exception:
        log.exception("callback %s failed", cq.data)
        toast = texts.TOAST_FAILED
    await cq.answer(toast or None)
