import asyncio

import settings
from tests.support import fake_claude as fc
from tests.support.helpers import feed, wait_for_text
from tests.support.updates import text_update


async def test_message_during_a_turn_is_queued_with_one_hint(app, spy, fake_claude):
    fake_claude.enqueue({"delay": 0.6}, fc.assistant_text("первый ответ"), fc.result())
    fake_claude.text_turn("второй ответ")
    fake_claude.text_turn("третий ответ")
    await feed(app, text_update("раз"))
    await asyncio.sleep(0.15)
    await feed(app, text_update("два"))
    await asyncio.sleep(0.15)   # past the batch window: a separate message, not one batch
    await feed(app, text_update("три"))
    await wait_for_text(spy, "третий ответ", timeout=5)
    texts = spy.sent_texts()
    assert texts.count("🕐 Дописываю текущий ход — это следующим.") == 1
    assert texts.index("первый ответ") < texts.index("второй ответ") < texts.index("третий ответ")
    assert fake_claude.stdin_texts() == ["раз", "два", "три"]


async def test_full_queue_rejects_new_messages(app, spy, fake_claude):
    settings.TURN_QUEUE_MAX = 1
    fake_claude.enqueue({"delay": 0.8}, fc.assistant_text("готово"), fc.result())
    fake_claude.text_turn("второй")
    await feed(app, text_update("раз"))
    await asyncio.sleep(0.15)
    await feed(app, text_update("два"))
    await asyncio.sleep(0.15)
    await feed(app, text_update("три"))
    await wait_for_text(spy, "⚠️ Очередь полна")
    await wait_for_text(spy, "второй", timeout=5)
    assert fake_claude.stdin_texts() == ["раз", "два"]
