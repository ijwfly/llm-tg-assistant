from tests.support.helpers import run
from tests.support.updates import text_update


async def test_whoami_shows_ids(app, spy):
    await run(app, text_update("/whoami", user_id=1, chat_id=1))
    spy.assert_shown_text_contains("Твой id: 1")
    spy.assert_shown_text_contains("Тема: —")


async def test_status_creates_topic_with_default_cwd(app, spy):
    await run(app, text_update("/status"))
    topics = await app.topics.list_all()
    assert len(topics) == 1 and topics[0]["cwd"] == "/work" and topics[0]["thread_id"] is None
    spy.assert_shown_text_contains("Директория   /work")
    assert topics[0]["permission_mode"] == "prompt"


async def test_topics_lists_known_topics(app, spy):
    await run(app, text_update("/topics"))
    assert spy.last_text() == "Пока пусто."
    await run(app, text_update("/status"))
    await run(app, text_update("/topics"))
    assert "/work" in spy.last_text()


async def test_forum_topic_message_creates_topic_bound_to_thread(app, spy):
    await run(app, text_update("/status", chat_id=-100500, chat_type="supergroup", thread_id=42, topic_name="proj"))
    topics = await app.topics.list_all()
    assert len(topics) == 1
    assert topics[0]["thread_id"] == 42 and topics[0]["chat_id"] == -100500 and topics[0]["title"] == "proj"
    reply = spy.calls("SendMessage")[-1]
    assert reply["message_thread_id"] == 42


async def test_reply_thread_in_plain_group_is_not_a_topic(app, spy):
    await run(app, text_update("/status", chat_id=-100500, chat_type="supergroup", thread_id=7, is_topic=False))
    topics = await app.topics.list_all()
    assert len(topics) == 1 and topics[0]["thread_id"] is None
    assert spy.calls("SendMessage")[-1].get("message_thread_id") is None


async def test_start_is_help(app, spy):
    await run(app, text_update("/start"))
    spy.assert_shown_text_contains("Каждая тема — своя сессия")


async def test_plain_text_registers_topic_and_answers_placeholder(app, spy):
    await run(app, text_update("привет"))
    assert len(await app.topics.list_all()) == 1
    spy.assert_shown_text_contains("🚧")
    user = await app.store.users.get(1)
    assert user and user["username"] == "tester"
