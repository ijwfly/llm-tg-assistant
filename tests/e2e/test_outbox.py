import asyncio

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import DeleteMessage, EditMessageText, SendMessage, SendRichMessage

import settings
from tests.support.helpers import run, wait_outbox_idle
from tests.support.updates import text_update


def _network_error():
    return TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="boom")


def _retry_after(seconds: int):
    return TelegramRetryAfter(method=SendMessage(chat_id=1, text="x"), message="flood", retry_after=seconds)


async def test_delivered_row_records_telegram_message_id(app, spy):
    await run(app, text_update("/help"))
    rows = await app.db.fetch("SELECT * FROM outbox")
    assert len(rows) == 1 and rows[0]["status"] == "delivered"
    assert rows[0]["delivered_message_id"] == 1000  # first id the recording session hands out


async def test_network_error_is_retried_until_delivered(app, spy, session):
    session.fail_next("SendMessage", _network_error())
    await run(app, text_update("/help"))
    assert len(spy.calls("SendMessage")) == 1 and len(session.failed_calls) == 1
    row = await app.db.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "delivered" and row["attempts"] == 1 and "boom" in row["last_error"]


async def test_rate_limit_delays_only_its_own_topic(app, spy, session):
    session.fail_next("SendMessage", _retry_after(1))
    await app.sender.send_text(1, None, "to topic A")
    await asyncio.sleep(0.15)  # A got its 429 and is parked
    await app.sender.send_text(2, None, "to topic B")
    await asyncio.sleep(0.3)
    assert spy.sent_texts(chat_id=2) == ["to topic B"]
    row_a = await app.db.fetchrow("SELECT status, attempts FROM outbox WHERE topic_key = '1:0'")
    assert row_a["status"] == "pending" and row_a["attempts"] == 0
    await asyncio.sleep(1.1)
    await wait_outbox_idle(app)
    assert spy.sent_texts(chat_id=1) == ["to topic A"]


async def test_order_is_preserved_within_a_topic(app, spy, session):
    session.fail_next("SendMessage", _network_error())
    for text in ("one", "two", "three"):
        await app.sender.send_text(1, None, text)
    await wait_outbox_idle(app)
    assert spy.sent_texts(chat_id=1) == ["one", "two", "three"]
    assert [p["text"] for _, p in session.failed_calls] == ["one"]


async def test_stale_row_is_marked_failed(app, spy, session):
    settings.OUTBOX_MAX_AGE_SECS = 0.0
    session.fail_next("SendMessage", _network_error())
    await app.sender.send_text(1, None, "late")
    await wait_outbox_idle(app)
    row = await app.db.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "failed" and "boom" in row["last_error"]
    assert spy.sent_texts() == []


async def test_rejected_rich_message_falls_back_to_plain_text(app, spy, session):
    session.fail_next("SendRichMessage", TelegramBadRequest(method=SendRichMessage(chat_id=1, rich_message={"markdown": "x"}),
                                                              message="Bad Request: can't parse rich message"))
    topic = await app.topics.get_or_create(__import__("app.core.topics", fromlist=["TopicRef"]).TopicRef(1, None))
    await app.sender.send_markdown(1, None, "# Заголовок\n\nтекст", topic_id=topic["id"], turn_id=None, role="assistant")
    await wait_outbox_idle(app)
    assert spy.calls("SendRichMessage") == []
    assert spy.sent_texts(chat_id=1) == ["# Заголовок\n\nтекст"]
    row = await app.db.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "delivered" and row["delivered_message_id"] == 1000
    link = await app.store.links.get(1, 1000)
    assert link and link["topic_id"] == topic["id"] and link["role"] == "assistant"


async def test_edit_to_identical_content_counts_as_delivered_and_does_not_block_the_queue(app, spy, session):
    session.fail_next("EditMessageText", TelegramBadRequest(
        method=EditMessageText(chat_id=1, message_id=5, text="x"),
        message="Bad Request: message is not modified: specified new message content and reply markup are exactly the same"))
    await app.sender.edit_text(1, None, 5, "same card")
    await app.sender.send_text(1, None, "after the edit")
    await wait_outbox_idle(app)
    rows = await app.db.fetch("SELECT method, status, attempts FROM outbox ORDER BY id")
    assert [(r["method"], r["status"], r["attempts"]) for r in rows] == [("EditMessageText", "delivered", 0),
                                                                         ("SendMessage", "delivered", 0)]
    assert spy.sent_texts(chat_id=1) == ["after the edit"]


async def test_permanent_bad_request_fails_the_row_and_lets_the_queue_flow(app, spy, session):
    session.fail_next("DeleteMessage", TelegramBadRequest(
        method=DeleteMessage(chat_id=1, message_id=5), message="Bad Request: message to delete not found"))
    await app.sender.delete(1, None, 5)
    await app.sender.send_text(1, None, "still delivered")
    await wait_outbox_idle(app)
    rows = await app.db.fetch("SELECT method, status FROM outbox ORDER BY id")
    assert [(r["method"], r["status"]) for r in rows] == [("DeleteMessage", "failed"), ("SendMessage", "delivered")]
    assert spy.sent_texts(chat_id=1) == ["still delivered"]
