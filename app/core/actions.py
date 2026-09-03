"""Topic actions shared by slash commands and inline buttons. Each returns a short toast text."""
from __future__ import annotations

import settings
from app.bridge.cli import PERMISSION_MODES
from app.core.runtime import QueueFull, TurnRequest
from app.render.keyboards import topic_card_kb
from app.transport import texts


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


async def topic_card(app, topic: dict) -> tuple[str, object]:
    rt = app.runtimes.peek(topic["id"])
    state = rt.status() if rt else None
    running = bool(state and (state.get("turn") is not None or state.get("queued")))
    staging = await app.store.staging.count(topic["id"])
    return texts.status(topic, state, staging), topic_card_kb(topic["id"], running=running)


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
